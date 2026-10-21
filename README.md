# Resultados electorales de Andalucía — API SIEL

Descargador reproducible de los resultados de las **elecciones al Parlamento de
Andalucía** que muestra [resultadoseleccionesandalucia.es](https://resultadoseleccionesandalucia.es/).
Consulta la API pública SIEL de la **Junta de Andalucía**, conserva sus respuestas
originales y genera CSV. No utiliza scraping de las tablas de la web.

- API: <https://ws040.juntadeandalucia.es/siel-api>
- Swagger: <https://ws040.juntadeandalucia.es/siel-api/swagger-ui.html>
- Especificación: <https://ws040.juntadeandalucia.es/siel-api/api-docs>

## Instalación

Python **3.11 o posterior**:

```sh
python3 -m pip install -r requirements.txt
```

## Comprobar disponibilidad sin descargar todas las mesas

Listar convocatorias:

```sh
python3 scripts/download_mesas.py --list-convocatorias
```

Comprobar todas las convocatorias con una muestra pequeña:

```sh
python3 scripts/download_mesas.py --check --all --retries 0 --output ./comprobacion
```

Comprobar únicamente 2026:

```sh
python3 scripts/download_mesas.py --check --convocatoria 202605 --output ./comprobacion-2026
```

`--check` consulta resúmenes y escrutinios de Andalucía y sus ocho provincias,
los mismos agregados CERA y **como máximo una mesa por provincia y convocatoria**.
No enumera el catálogo completo de mesas. Para buscar cada mesa explora como
máximo cinco municipios y una rama de distrito/sección por municipio. Tiene un
límite de 1.600 consultas lógicas de comprobación, además del descubrimiento
inicial de convocatorias; los reintentos HTTP de cada
consulta se controlan con `--retries`. Si se alcanza el límite, el informe marca
los ámbitos que no se pudieron comprobar.

El informe `check_siel.json` incluye respuestas, URLs, parámetros, incidencias,
selecciones sin distritos históricos y conciliaciones provinciales. Una muestra
satisfactoria **no acredita que todas las mesas sean correctas o estén disponibles**.
El comando devuelve 1 si encuentra incidencias o no puede completar alguna
comprobación. El HTTP 500 conocido del CERA de 1982 queda identificado en el
informe, sin provocar por sí solo un código de error. Un error general de conexión
antes de obtener el catálogo puede impedir crear el informe.

La conciliación de candidaturas compara sus etiquetas literales. Si la API
utiliza siglas o nombres diferentes entre ámbitos, señala
`etiquetas_no_comparables` y conserva las diferencias bajo sus nombres de origen.
No fusiona candidaturas por suposición ni atribuye automáticamente esas variantes
a votos perdidos. `issues_by_type` distingue estos casos de las inconsistencias
numéricas y los datos incompletos.

Las convocatorias se descubren automáticamente: no hay que añadir cada elección
al código. El 18 de octubre de 2026 estaban disponibles 13, de `198205` a `202605`.

## Descargar resultados

Prueba mínima de una mesa, con raw comprimido y archivos identificados como
parciales:

```sh
python3 scripts/download_mesas.py --convocatoria 202605 --limit-mesas 1 --compress-raw --output ./prueba
```

Una convocatoria completa:

```sh
python3 scripts/download_mesas.py --convocatoria 202605 --output ./datasets
```

Todas las convocatorias (descarga extensa, opcional):

```sh
python3 scripts/download_mesas.py --all --workers 6 --compress-raw --output ./datasets
```

La API no documenta una descarga masiva de todas las mesas. La descarga completa
consulta cada mesa y puede requerir bastante tiempo y espacio. El valor
predeterminado de concurrencia es seis; para comprobar disponibilidad usa `--check`.

Los directorios relativos de `--output` se resuelven desde la raíz del repositorio.
`--compress-raw` utiliza `.ndjson.gz` para nuevos archivos. Al reanudar se detecta y
conserva automáticamente el formato existente; no se mantienen dos copias del raw.
Los lectores y la reconstrucción de CSV admiten ambos formatos. No conviertas un
archivo existente dejando versiones comprimida y sin comprimir en la misma carpeta.

## Archivo exhaustivo: Parlamento de Andalucía y referendos

Para archivar todos los GET de datos y catálogos de ambos tipos, utiliza el
[descargador exhaustivo](docs/archivo-exhaustivo.md):

```sh
python3 scripts/archive_siel.py --output ./data --workers 6 --max-rps 6
```

Descubre las convocatorias de Parlamento de Andalucía (tipo 5) y referendos
(tipo 1). El 18 de octubre de 2026 eran 13 y 7, respectivamente. Primero descarga
mesas, CERA y agregados de **todas** las convocatorias; después las distribuciones
por candidatura y los reintentos transitorios. Genera CSV/NDJSON comprimidos tras
la primera fase de cada convocatoria y actualiza su manifiesto al finalizar.
No incluye los otros tipos electorales disponibles en la API.

La reanudación es automática sobre SQLite, sin `--resume`. Reutiliza también la
base creada por el anterior programa de la VPS, conservando respuestas y hashes.
No mezcles esta carpeta con los NDJSON del descargador `download_mesas.py`.

Consultar el estado sin hacer peticiones:

```sh
python3 scripts/archive_siel.py --output ./data --status
```

El trabajo se reparte por ámbitos pequeños con una cola de futuros limitada, de
modo que las mesas de un mismo municipio pueden descargarse en paralelo. Se
reutilizan conexiones y consultas; la compresión se realiza fuera del bloqueo de
SQLite. El límite de peticiones y `Retry-After` evitan acelerar a costa de repetir
errores de saturación. La latencia del origen puede seguir limitando el ritmo.

Para actualizar los derivados de un archivo exhaustivo ya terminado sin hacer
peticiones, usa `python3 scripts/archive_siel.py --output ./data --repair`.
La reparación separa las consultas sin desglose, conserva los fallos originales y
contrasta la cobertura con referencias oficiales cuando existen. Los reintentos
selectivos son explícitos y acotados; véase la documentación del archivo.

## Reanudación y ámbito

```sh
python3 scripts/download_mesas.py --all --resume --output ./datasets
```

Los registros ya obtenidos no se vuelven a consultar. Para reintentar también los
fallidos o incompletos:

```sh
python3 scripts/download_mesas.py --all --resume --retry-failed --output ./datasets
```

Los reintentos reemplazan el registro anterior sin añadir otra fila con su clave.
Las discrepancias aritméticas de respuestas completas no se reintentan por ser
incidencias del dato de origen. El CERA no disponible permanece sin nuevas
consultas salvo que se solicite `--retry-failed` o `--overwrite`.

El catálogo conserva metadatos de convocatoria, provincias, límite, finalización
de enumeración y huella de sus claves en `catalog_scope_<eleccion>.json`. Si se
quita un límite de prueba o se amplía la selección, el catálogo se vuelve a
construir. Los catálogos antiguos sin estos metadatos también se actualizan al
reanudar; esto puede requerir volver a enumerar, pero conserva las mesas válidas.

Para reducir el ámbito utiliza otra carpeta: se rechaza una reanudación cuyo raw
contenga registros fuera de la selección solicitada. `--province 18`, por ejemplo,
selecciona Granada. Una línea NDJSON dañada o una clave duplicada provocan un error
explícito; el programa no descarta silenciosamente esos datos.

## Archivos y cobertura

- `raw/mesas_<eleccion>.ndjson[.gz]`: respuestas originales de mesas y contexto.
- `raw/rausentes_<eleccion>.ndjson[.gz]`: CERA agregado para Andalucía y provincias.
- `processed/mesas_<eleccion>_catalog.csv`: catálogo de la selección.
- `processed/mesas_<eleccion>_long.csv`: una fila por mesa y candidatura disponible.
- `processed/mesas_<eleccion>_wide.csv`: una fila por mesa y columnas de candidaturas.
- `processed/andalucia_<eleccion>_completo.csv`: todas las mesas del catálogo
  enumerado sin filtros ni límite, más ocho registros CERA provinciales.
- `processed/andalucia_<eleccion>_parcial.csv`: selección limitada, provincial,
  sin CERA o cuya cobertura total no se puede acreditar con los metadatos.
- `processed/mesas_<eleccion>_incidencias.csv`: incidencias de descarga o calidad de mesas.
- `processed/calidad_<eleccion>.csv`: incidencias de calidad de mesas y CERA.
- `processed/rausentes_<eleccion>_long.csv` y `_wide.csv`: derivados CERA.
- `manifest_<eleccion>.json`: ámbito, cobertura, estados, recuentos y archivos.

El CSV combinado conserva todas las mesas de la selección y una fila CERA por
provincia. Excluye la fila CERA agregada de Andalucía para evitar duplicar el voto
exterior; esa respuesta sí permanece en el raw. Los votos desconocidos quedan
vacíos. Las columnas de candidaturas se ordenan de forma estable.

El nombre `_completo` describe **cobertura del catálogo**, no certifica la exactitud
de cada dato de origen. El manifiesto distingue:

- `coverage_complete`: catálogo sin filtros ni límite, ocho provincias y ocho
  registros provinciales CERA; claves presentes y únicas.
- `data_complete`: cobertura completa sin registros incompletos.
- `quality_ok`: no se han detectado datos incompletos ni inconsistencias.

Por tanto, un CSV con cobertura completa puede conservar incidencias y datos
desconocidos. Consulta siempre el manifiesto y el informe de calidad.

## Calidad del dato

Además de `fuente_registro`, `estado_descarga` y `error_descarga`, los CSV incluyen
`estado_calidad` (`ok`, `inconsistente` o `incompleto`) e `incidencias_calidad`.
Se comprueban la identidad territorial y de convocatoria, valores ausentes,
candidaturas duplicadas y estas igualdades:

```text
censo = votantes + abstenciones
votantes = válidos + nulos
válidos = blancos + candidaturas
suma de votos de candidaturas = votos a candidaturas
```

Los valores originales se conservan aunque no cuadren: no se corrigen ni imputan.
Los nombres y códigos de candidaturas de la API se conservan literalmente.
El HTTP 200 por sí solo no acredita la calidad de una respuesta.

La auditoría de octubre de 2026 encontró diferencias en agregados de 1990
(54 votos), tres mesas muestreadas de 1996 (1, 1 y 190 votos) y agregados de 2018
(17 votantes frente a válidos+nulos). No es una lista exhaustiva de incidencias.
El CERA de 1982 devuelve HTTP 500; se conservan filas provinciales con
`cera_no_disponible` y votos desconocidos vacíos. Si un resumen de mesa declara
cero votos y falla el escrutinio, se marca `resumen_cero_sin_escrutinio`: no se
certifica una abstención total ni se imputan votos por candidatura. Los antiguos
`ok_sin_votos` con errores también se marcan incompletos al exportar. Si faltan votos
por candidatura en una mesa no vacía, se marca `escrutinio_no_disponible`.

En 2026, el censo total del SIEL incluye CERA. Para comparar participación con
otras publicaciones hay que declarar el censo utilizado. Los votos de los
agregados consultados coincidieron con el BOJA 108/2026 y su corrección del
BOJA 115/2026; no se ha certificado cada mesa mediante un contraste externo.

## Reconstruir derivados sin consultar la red

```sh
python3 scripts/download_mesas.py --convocatoria 202605 --complete-only --output ./datasets
```

Exige raw y catálogo con claves únicas y exactamente coincidentes, y rechaza
registros de otras convocatorias, duplicados, ausencias y claves ajenas.
Los catálogos antiguos sin metadatos de alcance solo permiten una exportación
identificada como parcial. Para acreditar su ámbito utiliza `--resume`.
`--complete-only` no admite nuevos filtros ni límites. Con `--skip-rausentes`
excluye CERA incluso si existe un raw anterior, y la exportación es parcial.

## TLS y reintentos HTTP

La verificación TLS está **activada por defecto**. `--verify-tls` sigue siendo
válido por compatibilidad. Solo si una instalación necesita desactivarla de forma
explícita puede utilizar `--insecure`.

El cliente utiliza espera exponencial para errores transitorios y respeta
`Retry-After` en HTTP 429/503. Los errores HTTP permanentes, como 404, no se
reintentan. El parámetro `--retries` controla el número de reintentos por consulta.

## Pruebas

Las pruebas no descargan resultados electorales:

```sh
python3 -m unittest discover -s tests -v
```

GitHub Actions ejecuta la suite con Python 3.11 y 3.13.

## English

Reproducible downloader for **elections to the Parliament of Andalusia**, using
the public SIEL API provided by the **Junta de Andalucía**. Raw responses are
preserved as plain or gzip NDJSON, with normalized CSV exports and explicit
coverage and quality flags.

Use `--check --all` for a bounded availability and consistency check without
bulk polling-station downloads. Partial selections produce `_parcial.csv`.
`--resume --retry-failed` retries unsuccessful records without duplicate rows;
`--complete-only` validates unique identities and catalog coverage before export.
TLS verification is enabled by default. Source inconsistencies remain visible
and are never silently repaired.
