"""
Buscador bibliográfico OpenAlex + ERIC  ·  solo metadatos
==========================================================

Escribes una ecuación de búsqueda (en inglés, español, portugués... el idioma que
quieras) y la app la busca TAL CUAL en OpenAlex y en ERIC. No traduce nada.

Recupera solo metadatos: autores, año, título, resumen (abstract), DOI, URL, revista,
idioma, palabras clave, citas... No descarga texto completo.

Uso local:      streamlit run app.py
Despliegue:     ver README.md (GitHub + Streamlit Community Cloud)

El bloque "NÚCLEO" no depende de Streamlit: es el mismo código que usa el cuaderno de Colab.
"""

# <<<NUCLEO_INICIO>>>
# ======================================================================
# NÚCLEO (sin Streamlit)
# ======================================================================
import io
import html
import re
import time
import unicodedata
from difflib import SequenceMatcher

import pandas as pd
import requests

OA_URL = "https://api.openalex.org/works"
ERIC_URL = "https://api.ies.ed.gov/eric/"

# Columnas de la tabla final
COLUMNAS = ["record_id", "authors", "year", "title", "abstract", "doi", "url",
            "journal", "language", "keywords", "document_type", "cited_by_count",
            "oa_url", "issn", "eissn", "quartile", "subject_category", "quartile_year",
            "fuente"]
# Las que se muestran y se exportan en la hoja "resumen" por defecto
COLUMNAS_RESUMEN = ["authors", "year", "title", "abstract", "doi", "url",
                    "language", "journal", "quartile", "fuente"]

# Idiomas que se pueden filtrar (códigos de OpenAlex)
IDIOMAS_DISPONIBLES = {
    "en": "Inglés", "es": "Español", "pt": "Portugués", "zh": "Chino", "pl": "Polaco",
    "ru": "Ruso", "fr": "Francés", "de": "Alemán", "tr": "Turco", "id": "Indonesio",
    "it": "Italiano", "ja": "Japonés", "ko": "Coreano", "ar": "Árabe",
    "nl": "Neerlandés", "uk": "Ucraniano",
}
# ERIC escribe el idioma como nombre ("English"); OpenAlex como código ("en")
NOMBRES_IDIOMA = {
    "english": "en", "spanish": "es", "portuguese": "pt", "chinese": "zh", "polish": "pl",
    "russian": "ru", "french": "fr", "german": "de", "turkish": "tr", "indonesian": "id",
    "italian": "it", "japanese": "ja", "korean": "ko", "arabic": "ar", "dutch": "nl",
    "ukrainian": "uk",
}

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
ISSN_RE = re.compile(r"(E?ISSN)?[-:\s]*(\d{4}-?\d{3}[\dXx])", re.I)


class ErrorBusqueda(Exception):
    """Error pensado para mostrarse al usuario (nunca incluye claves)."""


def _log_print(msg, frac=None):
    print(msg)


# ---------------------------------------------------------------- utilidades
def limpiar(ecuacion):
    """Convierte la ecuación de varias líneas en una sola línea."""
    return " ".join(str(ecuacion).split())


def ocultar(texto, *secretos):
    """Tapa claves o correos que pudieran aparecer en un mensaje de error."""
    texto = str(texto)
    for s in secretos:
        if s:
            texto = texto.replace(s, "***")
    return texto


def norm_texto(s):
    """Minúsculas, sin tildes ni signos; conserva letras de cualquier alfabeto (ruso, chino...)."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", "", s)


def norm_issn(s):
    return re.sub(r"[^0-9Xx]", "", str(s or "")).upper()


def formato_issn(s):
    n = norm_issn(s)
    return f"{n[:4]}-{n[4:]}" if len(n) == 8 else None


def como_texto(x):
    """Listas -> texto separado por '; ' y decodifica entidades HTML."""
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        x = "; ".join(str(i) for i in x if i)
    x = html.unescape(str(x)).strip()
    return x or None


def doi_de(texto):
    m = DOI_RE.search(str(texto or ""))
    return m.group(0).rstrip(".,;)'\"") if m else None


def codigos_idioma(v):
    """Texto de idioma (código u nombre, uno o varios separados por ';') -> conjunto de códigos."""
    if not isinstance(v, str) or not v.strip():
        return set()
    return {NOMBRES_IDIOMA.get(x.strip().lower(), x.strip().lower()) for x in v.split(";") if x.strip()}


def normalizar_idioma(v):
    c = codigos_idioma(v)
    return "; ".join(sorted(c)) if c else None


# ---------------------------------------------------------------- ecuación
def partir_ecuacion(ecuacion):
    """Separa la ecuación en (consulta sin filtro de año, año_inicio, año_fin)."""
    e = limpiar(ecuacion)
    a = b = None
    m = re.search(r"publicationdateyear:\s*\[?\s*(\d{4})\s*(?:-|TO)\s*(\d{4})\s*\]?", e)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        e = e.replace(m.group(0), " ")
    e = re.sub(r"\s*\bAND\s*$", "", e.strip())
    e = re.sub(r"^\s*AND\b\s*", "", e)
    return e.strip(), a, b


def revisar_ecuacion(q):
    """Devuelve (errores, avisos). Los errores impiden buscar; los avisos solo advierten."""
    if not q or not q.strip():
        return ["La ecuación está vacía."], []
    errores, avisos = [], []
    if q.count('"') % 2:
        errores.append("Hay un número impar de comillas: cierra cada frase con comillas.")
    fuera = re.sub(r'"[^"]*"', '""', q)
    if fuera.count("(") != fuera.count(")"):
        errores.append("Los paréntesis no están balanceados.")
    tokens = re.findall(r"[^\s()]+", fuera)
    minus = sorted({t for t in tokens if t.lower() in ("and", "or", "not") and t != t.upper()})
    if minus:
        avisos.append("Los operadores deben ir en MAYÚSCULAS (AND, OR, NOT). Encontré: "
                      + ", ".join(minus) + ".")
    otros = sorted({t for t in tokens if t in ("Y", "O", "E", "OU", "NÃO", "NAO")})
    if otros:
        avisos.append("Los operadores son AND, OR y NOT, aunque escribas los términos en otro idioma. "
                      "Encontré: " + ", ".join(otros) + " (se buscarían como palabras).")
    return errores, avisos


# ---------------------------------------------------------------- HTTP seguro
def _get(url, params, secretos=(), headers=None, timeout=90, reintentos=3):
    """GET con reintentos. Si falla, el error NO deja ver claves (se levanta fuera del except)."""
    ultimo = None
    for i in range(reintentos):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            ultimo = ocultar(f"{type(e).__name__}: {e}", *secretos)[:300]
            time.sleep(2 * (i + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            ultimo = f"HTTP {r.status_code}"
            time.sleep(2 * (i + 1))
            continue
        return r
    raise ErrorBusqueda(f"No se pudo conectar con el servidor ({ultimo}).") from None


def _oa_get(url, extra, auth, timeout=90):
    params = {"mailto": auth["email"], "api_key": auth["api_key"]}
    params.update(extra)
    headers = {"User-Agent": f"BuscadorOpenAlexERIC/1.0 (mailto:{auth['email']})"}
    return _get(url, params, secretos=(auth["api_key"], auth["email"]), headers=headers, timeout=timeout)


def _error_oa(r, auth):
    detalle = ocultar(r.text[:300], auth["api_key"], auth["email"])
    if r.status_code in (401, 403):
        msg = "OpenAlex rechazó la API key (revisa que esté bien copiada)."
    elif r.status_code == 409:
        msg = "OpenAlex indica que falta la API key o que se agotaron los créditos del día."
    elif r.status_code == 400:
        msg = "OpenAlex no entendió la consulta (revisa comillas, paréntesis y AND/OR en mayúsculas)."
    else:
        msg = f"OpenAlex respondió HTTP {r.status_code}."
    return f"{msg} Detalle: {detalle}"


# ---------------------------------------------------------------- OpenAlex
def buscar_openalex(q, a, b, auth, max_registros=500, campo="title_and_abstract",
                    tipo="article", idiomas=None, log=_log_print):
    """Busca en OpenAlex. Devuelve (total_en_openalex, lista_de_obras)."""
    q = q.replace(",", " ")                      # la coma separa filtros en la API
    filtros, base = [], {}
    if campo == "default":
        base["search"] = q
    else:
        filtros.append(f"{campo}.search:{q}")
    if a:
        filtros.append(f"from_publication_date:{a}-01-01")
    if b:
        filtros.append(f"to_publication_date:{b}-12-31")
    if tipo:
        filtros.append(f"type:{tipo}")
    if idiomas:
        filtros.append("language:" + "|".join(idiomas))
    obras, cursor, total = [], "*", None
    while cursor and len(obras) < max_registros:
        extra = dict(base)
        extra.update({"filter": ",".join(filtros),
                      "per_page": min(200, max_registros - len(obras)), "cursor": cursor})
        if campo != "default":
            extra["sort"] = "cited_by_count:desc"
        r = _oa_get(OA_URL, extra, auth)
        if r.status_code != 200:
            if not obras:
                raise ErrorBusqueda(_error_oa(r, auth))
            log("OpenAlex se interrumpió; se conserva lo descargado hasta ahora.")
            break
        j = r.json()
        if total is None:
            total = (j.get("meta") or {}).get("count", 0)
            log(f"OpenAlex: {total:,} resultados en total.")
        res = j.get("results") or []
        if not res:
            break
        obras += res
        cursor = (j.get("meta") or {}).get("next_cursor")
        time.sleep(0.2)
    return (total or 0), obras[:max_registros]


def abstract_oa(inv):
    """OpenAlex entrega el resumen como índice invertido; lo reconstruye."""
    if not inv:
        return None
    pos = {}
    for palabra, lugares in inv.items():
        for i in lugares:
            pos[i] = palabra
    return " ".join(pos[i] for i in sorted(pos)) or None


def ficha_openalex(w):
    loc = w.get("primary_location") or {}
    fuente = loc.get("source") or {}
    kws = [k.get("display_name") for k in (w.get("keywords") or []) if k.get("display_name")]
    if not kws:
        kws = [t.get("display_name") for t in (w.get("topics") or []) if t.get("display_name")]
    autores = [(x.get("author") or {}).get("display_name") for x in (w.get("authorships") or [])]
    issns = [i for i in ([fuente.get("issn_l")] + list(fuente.get("issn") or [])) if i]
    oa = w.get("best_oa_location") or {}
    return {
        "record_id": (w.get("id") or "").rsplit("/", 1)[-1],
        "authors": como_texto([x for x in autores if x]),
        "year": w.get("publication_year"),
        "title": como_texto(w.get("title") or w.get("display_name")),
        "abstract": como_texto(abstract_oa(w.get("abstract_inverted_index"))),
        "doi": doi_de(w.get("doi")),
        "url": loc.get("landing_page_url") or w.get("doi") or w.get("id"),
        "journal": como_texto(fuente.get("display_name")),
        "language": normalizar_idioma(w.get("language")),
        "keywords": como_texto(kws),
        "document_type": como_texto(w.get("type")),
        "cited_by_count": w.get("cited_by_count"),
        "oa_url": oa.get("pdf_url") or oa.get("landing_page_url")
                  or (w.get("open_access") or {}).get("oa_url"),
        "issn": formato_issn(issns[0]) if issns else None,
        "eissn": None,
        "fuente": "OpenAlex",
        "_issns": issns,
    }


def obra_openalex(doi, auth):
    r = _oa_get(f"https://api.openalex.org/works/https://doi.org/{doi}", {}, auth, timeout=60)
    return r.json() if r.status_code == 200 else None


def buscar_por_titulo(titulo, anio, auth, umbral=0.90):
    """Si un registro de ERIC no trae DOI: lo busca en OpenAlex por título (año ±1) y valida similitud."""
    if not titulo:
        return None, 0
    extra = {"search": titulo, "per_page": 5}
    try:
        n = int(anio)
        extra["filter"] = f"publication_year:{n - 1}-{n + 1}"
    except (TypeError, ValueError):
        pass
    r = _oa_get(OA_URL, extra, auth, timeout=60)
    if r.status_code != 200:
        return None, 0
    mejor, mejor_s = None, 0
    for w in r.json().get("results", []):
        s = SequenceMatcher(None, norm_texto(titulo),
                            norm_texto(w.get("title") or w.get("display_name"))).ratio()
        if s > mejor_s:
            mejor, mejor_s = w, s
    return (mejor, mejor_s) if mejor_s >= umbral else (None, mejor_s)


# ---------------------------------------------------------------- ERIC
def _variantes_eric(q, a, b):
    base = q
    if a and b:
        yield f"{base} AND publicationdateyear:{a}-{b}"
        yield f"{base} AND publicationdateyear:[{a} TO {b}]"
    else:
        yield base


def buscar_eric(q, a, b, max_registros=500, por_pagina=100, log=_log_print):
    """Busca en ERIC. Devuelve (ecuación_usada, total_en_eric, lista_de_registros)."""
    for v in _variantes_eric(q, a, b):
        r = _get(ERIC_URL, {"search": v, "format": "json", "rows": min(por_pagina, max_registros),
                            "start": 0}, timeout=60)
        if r.status_code != 200:
            log(f"ERIC no aceptó esta forma de la ecuación (HTTP {r.status_code}); pruebo otra.")
            continue
        resp = r.json()["response"]
        total = resp.get("numFound", 0)
        log(f"ERIC: {total:,} resultados en total.")
        if total > 0:
            docs = list(resp["docs"])
            while len(docs) < min(total, max_registros):
                r2 = _get(ERIC_URL, {"search": v, "format": "json",
                                     "rows": min(por_pagina, max_registros - len(docs)),
                                     "start": len(docs)}, timeout=60)
                nuevo = r2.json()["response"]["docs"] if r2.status_code == 200 else []
                if not nuevo:
                    break
                docs += nuevo
                time.sleep(0.5)
            return v, total, docs[:max_registros]
    return None, 0, []


def sacar_doi(doc):
    for valor in (doc.get("url", ""), str(doc)):
        d = doi_de(valor)
        if d:
            return d
    return None


def issns_eric(doc):
    """(issn, eissn) a partir del campo 'issn' de ERIC (puede traer prefijo ISSN-/EISSN-)."""
    crudo = doc.get("issn")
    textos = crudo if isinstance(crudo, list) else ([crudo] if crudo else [])
    issn = eissn = None
    for t in textos:
        for pref, num in ISSN_RE.findall(str(t)):
            f = formato_issn(num)
            if not f:
                continue
            if pref.upper() == "EISSN":
                eissn = eissn or f
            else:
                issn = issn or f
    return issn, eissn


def ficha_eric(doc):
    eid = doc.get("id")
    issn, eissn = issns_eric(doc)
    doi = sacar_doi(doc)
    return {
        "record_id": eid,
        "authors": como_texto(doc.get("author")),
        "year": doc.get("publicationdateyear"),
        "title": como_texto(doc.get("title")),
        "abstract": como_texto(doc.get("description")),
        "doi": doi,
        "url": doc.get("url") or (f"https://eric.ed.gov/?id={eid}" if eid else None),
        "journal": como_texto(doc.get("source") or doc.get("journal")),
        "language": normalizar_idioma(como_texto(doc.get("language"))),
        "keywords": como_texto(doc.get("subject") or doc.get("descriptor") or doc.get("descriptors")),
        "document_type": como_texto(doc.get("publicationtype")),
        "cited_by_count": None,
        "oa_url": None,
        "issn": issn,
        "eissn": eissn,
        "fuente": "ERIC",
        "_issns": [i for i in (issn, eissn) if i],
    }


def completar_con_openalex(fila, w):
    """Rellena huecos de un registro de ERIC con lo que dice OpenAlex."""
    if not w:
        return fila
    ficha = ficha_openalex(w)
    for c in ("doi", "journal", "cited_by_count", "oa_url", "abstract", "language"):
        if not fila.get(c) and ficha.get(c):
            fila[c] = ficha[c]
    if not fila.get("issn") and ficha.get("issn"):
        fila["issn"] = ficha["issn"]
    fila["_issns"] = list(dict.fromkeys(fila.get("_issns", []) + ficha.get("_issns", [])))
    return fila


# ---------------------------------------------------------------- SCImago (opcional)
def cargar_sjr(origen):
    """Lee el CSV de SCImago (ruta o archivo subido). Devuelve {'issn': {...}, 'titulo': {...}}."""
    def leer(sep):
        if hasattr(origen, "seek"):
            origen.seek(0)
        return pd.read_csv(origen, sep=sep, dtype=str, encoding="utf-8-sig").fillna("")

    df_s = leer(";")
    if df_s.shape[1] < 3:                         # por si viene separado por comas
        df_s = leer(",")
    cols = {c.strip().lower(): c for c in df_s.columns}
    c_issn = cols.get("issn")
    c_q = next((cols[k] for k in cols if "best quartile" in k), None)
    c_tit = cols.get("title")
    c_cat = cols.get("categories")
    if not (c_issn and c_q):
        raise ErrorBusqueda("El CSV de SCImago no tiene las columnas 'Issn' y 'SJR Best Quartile'. "
                            "Descárgalo desde scimagojr.com/journalrank.php (botón 'Download data').")
    por_issn, por_titulo = {}, {}
    for _, r in df_s.iterrows():
        q = str(r[c_q]).strip().upper()
        info = {"quartile": q if q in ("Q1", "Q2", "Q3", "Q4") else None,
                "subject_category": (r[c_cat] if c_cat else None) or None}
        for i in re.split(r"[,;\s]+", str(r[c_issn])):
            n = norm_issn(i)
            if len(n) == 8:
                por_issn[n] = info
        if c_tit:
            por_titulo[norm_texto(r[c_tit])] = info
    return {"issn": por_issn, "titulo": por_titulo}


def aplicar_sjr(fila, sjr, anio):
    if not sjr:
        return fila
    info = None
    for i in fila.get("_issns", []):
        info = sjr["issn"].get(norm_issn(i))
        if info:
            break
    if not info:
        t = norm_texto(fila.get("journal"))
        info = sjr["titulo"].get(t) if t else None
    if info:
        fila["quartile"] = info["quartile"]
        fila["subject_category"] = info["subject_category"]
        fila["quartile_year"] = anio
    return fila


# ---------------------------------------------------------------- búsqueda completa
def ejecutar_busqueda(ecuacion, anio_desde=None, anio_hasta=None, email="", api_key="",
                      usar_openalex=True, usar_eric=True, max_openalex=500, max_eric=500,
                      campo="title_and_abstract", tipo="article", idiomas=None,
                      incluir_sin_idioma=True, sjr=None, sjr_anio=None,
                      completar_eric=False, log=_log_print):
    """
    Busca la ecuación TAL CUAL (sin traducir) en OpenAlex y/o ERIC y devuelve (df, info).
    Solo metadatos: no descarga texto completo.
    """
    q, a_eq, b_eq = partir_ecuacion(ecuacion)
    avisos = []
    a, b = anio_desde, anio_hasta
    if a is None and b is None:
        a, b = a_eq, b_eq
    elif a_eq:
        avisos.append("La ecuación traía un rango de años; se usó el de los selectores.")
    if a and b and a > b:
        a, b = b, a
    errores, avisos_q = revisar_ecuacion(q)
    if errores:
        raise ErrorBusqueda(" ".join(errores))
    avisos += avisos_q
    if not (usar_openalex or usar_eric):
        raise ErrorBusqueda("Elige al menos una fuente (OpenAlex o ERIC).")
    auth = {"email": (email or "").strip(), "api_key": (api_key or "").strip()}
    if usar_openalex and not (auth["email"] and auth["api_key"]):
        raise ErrorBusqueda("Para buscar en OpenAlex necesitas tu correo y tu API key.")
    idiomas = [i.lower() for i in (idiomas or [])]

    info = {"ecuacion": q, "anio_desde": a, "anio_hasta": b, "total_openalex": None,
            "descargados_openalex": 0, "total_eric": None, "descargados_eric": 0,
            "antes_filtro_idioma": 0, "unicos": 0, "avisos": avisos}
    filas, errores_fuente, obras_oa = [], [], []

    # --- OpenAlex ---
    if usar_openalex:
        log("Buscando en OpenAlex…", 0.05)
        try:
            api_idiomas = idiomas if (idiomas and not incluir_sin_idioma) else None
            total, obras_oa = buscar_openalex(q, a, b, auth, max_openalex, campo, tipo, api_idiomas, log)
            info["total_openalex"], info["descargados_openalex"] = total, len(obras_oa)
            filas += [ficha_openalex(w) for w in obras_oa]
            log(f"OpenAlex: {len(obras_oa):,} registros descargados.", 0.45)
            if total > max_openalex:
                avisos.append(f"OpenAlex tiene {total:,} resultados; se descargaron {max_openalex:,} "
                              "(los más citados). Sube el tope si quieres más.")
            if total == 0:
                avisos.append("OpenAlex devolvió 0 resultados: revisa la ecuación.")
        except ErrorBusqueda as e:
            errores_fuente.append(f"OpenAlex: {e}")
            log(f"⚠️ OpenAlex falló: {e}")

    # --- ERIC ---
    docs = []
    if usar_eric:
        log("Buscando en ERIC…", 0.5)
        try:
            usada, total, docs = buscar_eric(q, a, b, max_eric, log=log)
            info["total_eric"], info["descargados_eric"] = total, len(docs)
            log(f"ERIC: {len(docs):,} registros descargados.", 0.65)
            if total > max_eric:
                avisos.append(f"ERIC tiene {total:,} resultados; se descargaron {max_eric:,}.")
        except ErrorBusqueda as e:
            errores_fuente.append(f"ERIC: {e}")
            log(f"⚠️ ERIC falló: {e}")

    if errores_fuente and not filas and not docs:
        raise ErrorBusqueda(" | ".join(errores_fuente))
    avisos += errores_fuente

    # --- registros de ERIC (opcionalmente completados con OpenAlex) ---
    puede_completar = completar_eric and auth["email"] and auth["api_key"]
    if completar_eric and not puede_completar:
        avisos.append("Para completar ERIC con OpenAlex hacen falta el correo y la API key.")
    oa_por_doi = {doi_de(w.get("doi")).lower(): w for w in obras_oa if doi_de(w.get("doi"))}
    for n, doc in enumerate(docs, 1):
        fila = ficha_eric(doc)
        if puede_completar:
            try:
                if fila["doi"] and fila["doi"].lower() in oa_por_doi:
                    w = oa_por_doi[fila["doi"].lower()]
                elif fila["doi"]:
                    w = obra_openalex(fila["doi"], auth)
                    time.sleep(0.2)
                else:
                    w, _ = buscar_por_titulo(fila["title"], fila["year"], auth)
                    time.sleep(0.2)
                fila = completar_con_openalex(fila, w)
            except ErrorBusqueda:
                puede_completar = False
                avisos.append("Se dejó de completar ERIC con OpenAlex por un error de conexión.")
            if n % 25 == 0:
                log(f"Completando registros de ERIC con OpenAlex… {n}/{len(docs)}",
                    0.65 + 0.25 * n / max(len(docs), 1))
        filas.append(fila)

    # --- tabla ---
    log("Uniendo resultados y quitando duplicados…", 0.92)
    if sjr:
        filas = [aplicar_sjr(f, sjr, sjr_anio) for f in filas]
    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=COLUMNAS), info
    for c in COLUMNAS:
        if c not in df.columns:
            df[c] = None
    # Clave de duplicado: el DOI; si no hay, el título (y si ese título ya aparece con DOI, ese DOI)
    titulo_a_doi = {}
    for d, t in zip(df["doi"], df["title"]):
        if isinstance(d, str) and d and norm_texto(t):
            titulo_a_doi.setdefault(norm_texto(t), d.lower())
    claves = []
    for d, t, rid in zip(df["doi"], df["title"], df["record_id"]):
        nt = norm_texto(t)
        if isinstance(d, str) and d:
            claves.append(d.lower())
        elif nt in titulo_a_doi:
            claves.append(titulo_a_doi[nt])
        else:
            claves.append(nt or f"id:{rid}")
    df["_clave"] = claves
    df["_orden_fuente"] = (df["fuente"] == "ERIC").astype(int)        # OpenAlex primero
    df = df.sort_values("_orden_fuente", kind="stable")
    agg = {c: "first" for c in COLUMNAS}                              # 'first' toma el primer dato no vacío
    agg["fuente"] = lambda s: " + ".join(sorted(set(s)))
    df = df.groupby("_clave", sort=False).agg(agg).reset_index(drop=True)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["cited_by_count"] = pd.to_numeric(df["cited_by_count"], errors="coerce").astype("Int64")
    df["quartile_year"] = pd.to_numeric(df["quartile_year"], errors="coerce").astype("Int64")
    info["antes_filtro_idioma"] = len(df)

    # --- filtro por idioma ---
    if idiomas:
        permitidos = set(idiomas)
        cods = df["language"].map(codigos_idioma)
        mascara = cods.map(lambda c: bool(c & permitidos) or (incluir_sin_idioma and not c))
        df = df[mascara]
    df = df.sort_values(["year", "title"], ascending=[False, True], na_position="last").reset_index(drop=True)
    df = df[COLUMNAS]
    info["unicos"] = len(df)
    log(f"Listo: {len(df):,} artículos únicos.", 1.0)
    return df, info


# ---------------------------------------------------------------- exportar
def _recortar(df):
    """Excel admite como máximo ~32 000 caracteres por celda."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda v: v[:32000] if isinstance(v, str) else v)
    return out


def a_excel(df, columnas=None, hoja_por_idioma=True):
    """Devuelve el Excel (bytes): hoja 'completo', hoja 'resumen' y, opcional, una hoja por idioma."""
    columnas = [c for c in (columnas or COLUMNAS_RESUMEN) if c in df.columns]
    completo = _recortar(df)
    resumen = completo[columnas]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        completo.to_excel(xw, sheet_name="completo", index=False)
        resumen.to_excel(xw, sheet_name="resumen", index=False)
        if hoja_por_idioma and "language" in resumen.columns:
            usados = {"completo", "resumen"}
            for cod, g in resumen.groupby(resumen["language"].fillna("sin_idioma")):
                nombre = re.sub(r"[:\\/?*\[\]]", "-", str(cod))[:31] or "sin_idioma"
                base, k = nombre, 2
                while nombre in usados:
                    nombre = f"{base[:28]}_{k}"
                    k += 1
                usados.add(nombre)
                g.to_excel(xw, sheet_name=nombre, index=False)
    return buf.getvalue()


def a_csv(df, columnas=None):
    columnas = [c for c in (columnas or COLUMNAS_RESUMEN) if c in df.columns]
    return df[columnas].to_csv(index=False).encode("utf-8-sig")
# <<<NUCLEO_FIN>>>


# ======================================================================
# INTERFAZ STREAMLIT
# ======================================================================
EJEMPLOS = {
    "Inglés": '("organizational citizenship behavior" OR "extra-role behavior" OR OCB) '
              'AND ("organizational commitment" OR "affective commitment" OR "normative commitment")',
    "Español": '("comportamiento de ciudadanía organizacional" OR "ciudadanía organizacional") '
               'AND ("compromiso organizacional" OR "compromiso afectivo" OR "compromiso normativo")',
    "Portugués": '("comportamento de cidadania organizacional" OR "cidadania organizacional") '
                 'AND ("comprometimento organizacional" OR "comprometimento afetivo" OR "comprometimento normativo")',
    "Mezcla (3 idiomas)": '("organizational citizenship behavior" OR "comportamiento de ciudadanía organizacional" '
                          'OR "comportamento de cidadania organizacional") '
                          'AND ("organizational commitment" OR "compromiso organizacional" '
                          'OR "comprometimento organizacional")',
}


def main():
    import streamlit as st
    from datetime import date

    st.set_page_config(page_title="Buscador OpenAlex + ERIC", page_icon="📚", layout="wide")
    st.title("📚 Buscador bibliográfico OpenAlex + ERIC")
    st.caption("Recupera solo metadatos (autores, año, título, resumen, DOI, URL…). "
               "No descarga texto completo.")

    anio_actual = date.today().year
    if "ecuacion" not in st.session_state:
        st.session_state["ecuacion"] = EJEMPLOS["Inglés"]

    # ------------------------------------------------------------ barra lateral
    with st.sidebar:
        st.header("1. Credenciales de OpenAlex")
        email = st.text_input("Correo electrónico", placeholder="tu@correo.com")
        api_key = st.text_input("API key de OpenAlex", type="password",
                                help="Gratuita: crea una cuenta en openalex.org y cópiala desde Ajustes > API.")
        st.caption("Se usan solo durante esta sesión. La app no las guarda.")

        st.header("2. Fuentes")
        usar_oa = st.checkbox("OpenAlex (todas las áreas)", value=True)
        usar_eric = st.checkbox("ERIC (educación)", value=True)

        st.header("3. Filtros")
        filtrar_anio = st.checkbox("Filtrar por año", value=True)
        c1, c2 = st.columns(2)
        anio_desde = c1.number_input("Desde", 1900, anio_actual, 2020, disabled=not filtrar_anio)
        anio_hasta = c2.number_input("Hasta", 1900, anio_actual + 1, anio_actual, disabled=not filtrar_anio)
        etiquetas = {f"{n} ({c})": c for c, n in IDIOMAS_DISPONIBLES.items()}
        elegidos = st.multiselect("Idiomas de los artículos (vacío = todos)", list(etiquetas))
        incluir_sin_idioma = st.checkbox("Incluir artículos sin idioma detectado", value=True)

        st.header("4. Opciones")
        max_oa = st.number_input("Máx. registros de OpenAlex", 50, 5000, 500, step=50)
        max_eric = st.number_input("Máx. registros de ERIC", 50, 5000, 500, step=50)
        campo = st.selectbox("Dónde buscar en OpenAlex",
                             ["title_and_abstract", "default"],
                             format_func=lambda x: "Título y resumen (preciso)" if x == "title_and_abstract"
                             else "Todo, incluso texto indexado (más resultados, más ruido)")
        tipo = st.selectbox("Tipo de documento (OpenAlex)", ["article", None],
                            format_func=lambda x: "Solo artículos" if x else "Todos (libros, capítulos…)")
        completar = st.checkbox("Completar ERIC con OpenAlex (DOI, revista…)", value=False,
                                help="Busca cada registro de ERIC en OpenAlex. Es más lento.")

        st.header("5. Cuartiles (opcional)")
        sjr_file = st.file_uploader("CSV de SCImago", type=["csv"],
                                    help="Descárgalo en scimagojr.com/journalrank.php (botón 'Download data'). "
                                         "Si no lo subes, la columna 'quartile' queda vacía.")
        sjr_anio = st.number_input("Año de la edición de SCImago", 1999, anio_actual, 2024)

    # ------------------------------------------------------------ ecuación
    st.subheader("Ecuación de búsqueda")
    st.write("Escríbela en el idioma de los artículos que buscas, o mezcla idiomas con `OR`. "
             "**La app no traduce nada**: busca exactamente lo que escribas. "
             "Operadores en MAYÚSCULAS (`AND`, `OR`, `NOT`), frases entre comillas, grupos con paréntesis.")
    cols = st.columns(len(EJEMPLOS))
    for col, (nombre, texto) in zip(cols, EJEMPLOS.items()):
        col.button(f"Ejemplo: {nombre}", on_click=lambda t=texto: st.session_state.update(ecuacion=t),
                   width="stretch")
    ecuacion = st.text_area("Ecuación", key="ecuacion", height=130, label_visibility="collapsed")

    q_preview, _, _ = partir_ecuacion(ecuacion)
    errores, avisos = revisar_ecuacion(q_preview)
    for e in errores:
        st.error(e)
    for a in avisos:
        st.warning(a)

    # ------------------------------------------------------------ ejecutar
    if st.button("🔎 Buscar", type="primary", disabled=bool(errores)):
        email_ok = bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))
        if not (usar_oa or usar_eric):
            st.error("Elige al menos una fuente.")
        elif usar_oa and not (email_ok and api_key.strip()):
            st.error("Para buscar en OpenAlex escribe un correo válido y tu API key (barra lateral).")
        else:
            with st.status("Buscando…", expanded=True) as status:
                barra = st.progress(0.0)

                def log(msg, frac=None):
                    st.write(msg)
                    if frac is not None:
                        barra.progress(min(max(float(frac), 0.0), 1.0))

                try:
                    sjr = cargar_sjr(sjr_file) if sjr_file is not None else None
                    df, info = ejecutar_busqueda(
                        ecuacion, int(anio_desde) if filtrar_anio else None,
                        int(anio_hasta) if filtrar_anio else None,
                        email=email, api_key=api_key, usar_openalex=usar_oa, usar_eric=usar_eric,
                        max_openalex=int(max_oa), max_eric=int(max_eric), campo=campo, tipo=tipo,
                        idiomas=[etiquetas[e] for e in elegidos], incluir_sin_idioma=incluir_sin_idioma,
                        sjr=sjr, sjr_anio=int(sjr_anio), completar_eric=completar, log=log)
                    st.session_state["resultado"] = {"df": df, "info": info}
                    status.update(label="Búsqueda terminada", state="complete", expanded=False)
                except ErrorBusqueda as e:
                    status.update(label="No se pudo completar la búsqueda", state="error")
                    st.error(ocultar(e, api_key, email))
                except Exception as e:  # nunca mostrar el traceback: podría contener la clave
                    status.update(label="Error inesperado", state="error")
                    st.error(ocultar(f"Error inesperado ({type(e).__name__}): {e}", api_key, email))

    # ------------------------------------------------------------ resultados
    res = st.session_state.get("resultado")
    if res:
        df, info = res["df"], res["info"]
        st.divider()
        st.subheader("Resultados")
        m = st.columns(4)
        m[0].metric("Artículos únicos", f"{len(df):,}")
        m[1].metric("OpenAlex (descargados)", f"{info['descargados_openalex']:,}",
                    help=f"Total en OpenAlex: {info['total_openalex']}")
        m[2].metric("ERIC (descargados)", f"{info['descargados_eric']:,}",
                    help=f"Total en ERIC: {info['total_eric']}")
        m[3].metric("Quitados por idioma", f"{info['antes_filtro_idioma'] - info['unicos']:,}")
        for a in info["avisos"]:
            st.info(a)

        if df.empty:
            st.warning("No hay resultados con estos criterios. Prueba otra ecuación o quita filtros.")
        else:
            visibles = st.multiselect("Columnas a mostrar y exportar", COLUMNAS,
                                      default=COLUMNAS_RESUMEN)
            vista = df[visibles] if visibles else df[COLUMNAS_RESUMEN]
            st.dataframe(vista, width="stretch", hide_index=True, height=480,
                         column_config={"url": st.column_config.LinkColumn("url"),
                                        "oa_url": st.column_config.LinkColumn("oa_url")})
            idi = df["language"].fillna("sin idioma").value_counts()
            with st.expander("Artículos por idioma"):
                st.bar_chart(idi)
            hoja_idioma = st.checkbox("Excel: una hoja por idioma", value=True)
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Descargar Excel", data=a_excel(df, visibles, hoja_idioma),
                               file_name="resultados.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            d2.download_button("⬇️ Descargar CSV", data=a_csv(df, visibles),
                               file_name="resultados.csv", mime="text/csv")

    st.divider()
    st.caption("Datos: OpenAlex (CC0) y ERIC (Institute of Education Sciences). Los cuartiles provienen del "
               "CSV de SCImago que tú subas. La app no almacena tus credenciales ni tus búsquedas.")


if __name__ == "__main__":
    main()
