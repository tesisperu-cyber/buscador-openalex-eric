# 📚 Buscador bibliográfico OpenAlex + ERIC

App de Streamlit (y cuaderno de Colab) para buscar literatura científica en **OpenAlex** y **ERIC** con una sola ecuación de búsqueda.

- Escribes la ecuación **en el idioma que quieras** (inglés, español, portugués, chino, polaco…) o mezclas idiomas con `OR`.
- **No traduce nada** ni usa ningún traductor: busca exactamente lo que escribes.
- Recupera **solo metadatos**: autores, año, título, resumen (abstract), DOI, URL, revista, idioma, palabras clave y número de citas. **No descarga texto completo.**
- Cada persona usa **su propio correo y su propia API key de OpenAlex**.
- Opcional: sube tu CSV de **SCImago** para añadir el cuartil de la revista (Q1–Q4).
- Filtra por año y por idioma, une OpenAlex + ERIC sin duplicados y exporta a **Excel** (con una hoja por idioma) o **CSV**.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `app.py` | La app de Streamlit (incluye toda la lógica de búsqueda). |
| `buscador_openalex_eric.ipynb` | El mismo buscador como cuaderno de Google Colab. |
| `requirements.txt` | Librerías que necesita la app. |
| `README.md` | Este archivo. |
| `.gitignore` | Evita subir claves, resultados y CSV a GitHub. |

## 1. Conseguir la API key de OpenAlex

1. Crea una cuenta gratuita en [openalex.org](https://openalex.org).
2. Copia tu clave desde [openalex.org/settings/api](https://openalex.org/settings/api).

Según el anuncio oficial de OpenAlex (enero de 2026), a partir del 13 de febrero de 2026 la API exige una API key gratuita, y el parámetro de correo ya no se usa para la "polite pool". La app pide el correo igualmente para identificar tus consultas (cabecera `User-Agent`). Si algo de esto cambia, consulta la documentación de OpenAlex.

## 2. Usar el cuaderno en Google Colab

1. Sube `buscador_openalex_eric.ipynb` a [colab.research.google.com](https://colab.research.google.com) (Archivo → Subir cuaderno).
2. Ejecuta las celdas en orden.
3. En la celda de credenciales escribe tu correo. La API key puedes guardarla en 🔑 **Secretos** con el nombre `OPENALEX_KEY`; si no, el cuaderno te la pide con la escritura oculta.
4. Cambia la ecuación y los filtros en la sección 3, busca y descarga el Excel.

## 3. Probar la app en tu computadora

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`.

## 4. Subir el proyecto a GitHub

Crea un repositorio vacío en GitHub (por ejemplo `buscador-openalex-eric`) y luego, en la carpeta del proyecto:

```bash
git init
git add app.py requirements.txt README.md .gitignore buscador_openalex_eric.ipynb
git commit -m "Buscador OpenAlex + ERIC"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/buscador-openalex-eric.git
git push -u origin main
```

> ⚠️ **Nunca subas una API key** al repositorio. La app no la necesita guardada: cada usuario la escribe en la barra lateral y solo vive mientras dura su sesión.

## 5. Desplegar en Streamlit Community Cloud

1. Entra en [share.streamlit.io](https://share.streamlit.io) e inicia sesión con tu cuenta de GitHub.
2. Pulsa **Create app** y elige la opción de desplegar desde un repositorio de GitHub.
3. Elige tu repositorio, la rama `main` y como archivo principal `app.py`.
4. Pulsa **Deploy**. En uno o dos minutos tendrás una URL pública para compartir.

No hace falta configurar *Secrets*: no pongas tu clave allí si la app es pública, porque entonces todos los visitantes gastarían tus créditos de OpenAlex.

## 6. Cómo usar la app

1. En la barra lateral escribe tu **correo** y tu **API key de OpenAlex**.
2. Elige las fuentes (OpenAlex, ERIC), el rango de años y, si quieres, los idiomas de los artículos.
3. (Opcional) Sube el CSV de SCImago: se descarga en [scimagojr.com/journalrank.php](https://www.scimagojr.com/journalrank.php) con el botón *Download data*.
4. Escribe la ecuación (o pulsa uno de los ejemplos) y pulsa **Buscar**.
5. Revisa la tabla y descarga el **Excel** o el **CSV**.

### Sintaxis de la ecuación

- Operadores en **MAYÚSCULAS**: `AND`, `OR`, `NOT` (aunque los términos estén en español o portugués).
- Frases exactas entre **comillas**: `"compromiso organizacional"`.
- Grupos con **paréntesis**.
- El rango de años se controla con los selectores de la barra lateral.

Ejemplos:

```text
Inglés:
("organizational citizenship behavior" OR OCB) AND ("organizational commitment" OR "affective commitment")

Español:
("comportamiento de ciudadanía organizacional") AND ("compromiso organizacional" OR "compromiso afectivo")

Portugués:
("comportamento de cidadania organizacional") AND ("comprometimento organizacional" OR "comprometimento afetivo")

Mezcla de idiomas en una sola búsqueda:
("organizational citizenship behavior" OR "comportamiento de ciudadanía organizacional" OR "comportamento de cidadania organizacional")
AND ("organizational commitment" OR "compromiso organizacional" OR "comprometimento organizacional")
```

Como la app no traduce, para recuperar artículos en varios idiomas escribe los términos en cada idioma y únelos con `OR`.

## Columnas de la tabla

`authors`, `year`, `title`, `abstract`, `doi`, `url`, `journal`, `language`, `keywords`, `document_type`, `cited_by_count`, `oa_url` (enlace a una versión abierta, si existe), `issn`, `eissn`, `quartile`, `subject_category`, `quartile_year`, `fuente` (OpenAlex, ERIC o ambas) y `record_id`.

El Excel tiene una hoja `completo` (todas las columnas), una hoja `resumen` (las columnas que elijas) y, si lo activas, una hoja por idioma.

## Limitaciones a tener en cuenta

- **Solo metadatos.** No se descarga ni se procesa texto completo.
- **Tope de registros.** OpenAlex se ordena por citas (de más a menos), así que si hay más resultados que el tope, se descargan los más citados.
- **Idioma.** OpenAlex lo detecta automáticamente a partir del título y el resumen y a veces falla o lo deja vacío; por eso existe la opción *Incluir artículos sin idioma detectado*.
- **ERIC** indexa solo educación y casi todo está en inglés: los términos en otros idiomas aportan poco ahí, pero no estorban.
- **Chino, ruso y otros alfabetos.** La búsqueda por frase exacta puede comportarse distinto con idiomas sin espacios entre palabras; si una búsqueda da 0 resultados, prueba con términos sueltos.
- **Cuartiles.** Se asignan por ISSN y, si no, por título exacto de la revista; las revistas que no estén en tu CSV quedan sin cuartil.
- **Duplicados.** Se eliminan por DOI o, si no hay, por título normalizado.

## Privacidad

- El correo y la API key se usan solo para las consultas a OpenAlex durante la sesión. La app no los guarda, no los escribe en archivos y los oculta de los mensajes de error.
- La app no almacena tus ecuaciones ni tus resultados.

## Solución de problemas

| Mensaje | Qué hacer |
|---|---|
| *OpenAlex rechazó la API key* | Vuelve a copiarla desde openalex.org/settings/api, sin espacios. |
| *Falta la API key o se agotaron los créditos* | Revisa que la hayas pegado y que no hayas superado el límite diario de tu cuenta. |
| *OpenAlex no entendió la consulta* | Revisa comillas, paréntesis y que `AND`/`OR` estén en mayúsculas. |
| 0 resultados | Quita filtros (idioma, año) o simplifica la ecuación. |
| *Los paréntesis no están balanceados* | Cada `(` necesita su `)`. |

## Créditos

- Datos de [OpenAlex](https://openalex.org) (licencia CC0) y [ERIC](https://eric.ed.gov) (Institute of Education Sciences).
- Los cuartiles provienen del archivo de [SCImago Journal & Country Rank](https://www.scimagojr.com) que cada usuario sube; no se incluye ningún CSV en este repositorio.

Añade al repositorio el archivo `LICENSE` que prefieras antes de hacerlo público.
