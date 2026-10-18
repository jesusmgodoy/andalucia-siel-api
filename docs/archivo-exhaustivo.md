# Archivo exhaustivo de SIEL

`scripts/archive_siel.py` archiva los GET de datos y opciones de Parlamento de
Andalucía (5) y referendos (1), exclusivamente para Andalucía (`cautonoma=1`).
Necesita Python 3.11+, requests y Linux/macOS (bloqueo de instancia con `flock`).
No solicita los tres POST de conversión JSON a XML: no aportan nuevos datos.

## Ejecución y rendimiento

```sh
python3 -m pip install -r requirements.txt
python3 scripts/archive_siel.py --output ./data --workers 6 --max-rps 6
```

`--output` se resuelve desde el directorio de ejecución. La descarga es extensa;
conviene ejecutarla en un servidor con espacio disponible. Se detiene con menos
de 20 GiB libres; `--reserve-gib` permite cambiar esa reserva. `--timeout 45`
controla la espera de lectura HTTP, además de 10 segundos para conectar. La
verificación TLS está siempre activa.

La planificación sigue este orden:

1. Mesas, CERA y resúmenes/escrutinios de Andalucía, provincias, municipios,
   distritos y secciones de todas las convocatorias. Exportación tras cada una.
2. Catálogos de candidaturas, distribuciones por candidatura y electos.
3. Reintentos de consultas transitorias fallidas, hasta tres intentos totales por
   consulta. Si se recupera un catálogo, se recorren sus ramas antes de finalizar.
4. Actualización final de exportaciones y manifiestos.

Las tareas se reparten por provincia, municipio, distrito, sección y mesa. Un
municipio grande puede ocupar varios trabajadores. Nunca hay más de dos futuros
pendientes por trabajador; los trabajadores devuelven nuevos ámbitos al
planificador y no esperan a otros futuros. Los fallos se guardan en SQLite y no
ocupan un trabajador esperando su reintento durante la fase inicial.

`--workers` admite de 1 a 16 y controla las conexiones simultáneas. `--max-rps`
limita globalmente el inicio de peticiones, incluidos los reintentos. Ambos
límites son independientes: más trabajadores ayudan cuando hay latencia, pero
no aumentan el máximo de peticiones por segundo. HTTP 429/503 aplica una pausa
global y respeta `Retry-After`, también para trabajadores que ya estaban esperando.
Los errores permanentes (por ejemplo 404) no se repiten automáticamente.

No existe una velocidad mínima garantizada: un servidor que tarda 30 segundos
en responder sigue imponiendo ese coste. El progreso incluye la duración de las
consultas recientes para distinguir ese caso de un problema local.

## Estado y reanudación

```sh
python3 scripts/archive_siel.py --output ./data --status
cat data/progress.json
```

El estado muestra fase, convocatoria, mesas identificadas, mesas con ambas
respuestas recibidas, convocatorias exportadas/finalizadas, reintentos y consultas
en curso. `recent_endpoints` incluye duración media y fallos de las últimas 500
peticiones de esta ejecución. Es un recuento de respuestas HTTP/JSON válidas; los
controles de calidad son independientes. No se presenta un porcentaje con un
denominador que todavía está creciendo.

Para reanudar, ejecuta el mismo comando y carpeta. Las respuestas satisfactorias
no se solicitan de nuevo, tampoco al repetir una fase interrumpida. Un único
proceso puede escribir la carpeta. SIGTERM/Ctrl+C solicita una parada controlada;
la petición en curso puede tardar hasta el timeout en terminar. Los puntos de
control se escriben únicamente al completar su fase/exportación.

Para volver a intentar consultas que agotaron su presupuesto, incluidos los
fallos permanentes:

```sh
python3 scripts/archive_siel.py --output ./data --retry-unavailable
```

Esto reinicia el presupuesto de los fallos, mantiene el historial de intentos y
reutiliza los éxitos. El recorrido es finito incluso si el origen sigue fallando.

Para descubrir convocatorias nuevas en una carpeta ya utilizada:

```sh
python3 scripts/archive_siel.py --output ./data --refresh-catalogs
```

Actualiza la especificación y los catálogos iniciales de ámbitos, tipos,
provincias y fechas. Los catálogos territoriales por convocatoria y las respuestas
ya descargadas se conservan. Sin esta opción, se reutiliza la instantánea de
metadatos iniciales, lo que permite reanudar sin peticiones repetidas.

## Archivos y garantías

- `archivo.sqlite3`: referencia principal. Conserva bytes originales comprimidos,
  SHA-256, URL, parámetros, fechas, respuestas e historial de intentos. Las nuevas
  duraciones se guardan en `attempts.duration_ms`; los intentos antiguos quedan
  con duración desconocida.
- `plan.json`, `api_docs.json`: ámbito y especificación consultados; el plan
  registra también versión Git, hash del programa y configuración de recursos.
- `progress.json`: estado periódico; `finished.json`: recorrido finalizado,
  aunque existan errores del origen. Consulta siempre sus recuentos y manifiestos.
- `t5/<fecha>/` y `t1/<fecha>/`: `respuestas.ndjson.gz`, `mesas.ndjson.gz`,
  `cera.ndjson.gz`, catálogo de mesas, CSV largos y combinado, resúmenes,
  escrutinios y `manifest.json`.
- `metadatos.ndjson.gz`: representación portátil de las respuestas sin fecha.

SQLite conserva los bytes exactos; el NDJSON es su representación JSON portátil.
No borres SQLite para ahorrar espacio mientras se ejecuta o si necesitas
reanudar o verificar los hashes de los bytes originales.

Las exportaciones se construyen en archivos temporales, se reemplazan por
archivo y publican el manifiesto al final. Una excepción durante su construcción
conserva los archivos publicados anteriormente. No se garantiza una transacción
atómica del conjunto de archivos ante una pérdida de energía durante la
publicación; reanudar reconstruye la exportación que no alcanzó su punto de control.

`stage=core` y `archive_finished=false` indican una exportación anticipada que
todavía no incluye todas las vistas. `stage=final` indica que terminó el recorrido
y su presupuesto de reintentos. `_completo` y `catalog_coverage_complete` requieren
catálogo sin ramas inaccesibles y coincidencia con `nummesas` del agregado de
Andalucía. `mesa_data_complete` exige además ambas respuestas de cada mesa;
`data_complete` exige finalización y ninguna consulta archivada no disponible.
Estas marcas no certifican la coherencia aritmética del origen. Los CSV reutilizan
los controles de calidad del descargador de mesas, sin corregir ni imputar votos.
El combinado añade CERA provincial y excluye el CERA agregado para evitar duplicarlo.

## Servicio en una VPS

La [unidad de ejemplo](../deploy/andalucia-siel-download.service) utiliza
`/home/ubuntu/elecciones-andalucia`, su entorno `.venv`, usuario `ubuntu`,
`data/` y `logs/`. Adapta las rutas antes de instalarla si tu despliegue difiere.
No requiere paquetes adicionales aparte de las dependencias del repositorio.

```sh
mkdir -p data logs
sudo cp deploy/andalucia-siel-download.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now andalucia-siel-download.service
systemctl status andalucia-siel-download.service --no-pager
python3 scripts/archive_siel.py --output ./data --status
tail -f logs/download.log
```

La unidad limita CPU/memoria, reserva espacio libre y reinicia fallos del proceso
pasados cinco minutos. Las indisponibilidades del origen quedan archivadas y no
implican por sí solas un fallo del servicio. Detención:

```sh
sudo systemctl stop andalucia-siel-download.service
```

## Migración del programa anterior de la VPS

Detén primero el servicio antiguo. Haz una copia de seguridad de SQLite mediante
`sqlite3.Connection.backup()` o con la base cerrada y sus WAL correctamente
incorporados; copiar únicamente un `.sqlite3` abierto puede omitir datos del WAL.
Conserva también la unidad y el programa antiguos para poder restaurarlos.

Actualiza el repositorio y cambia `ExecStart` a `scripts/archive_siel.py`, dejando
**la misma carpeta de datos**. La migración añade tablas/columnas; no elimina
respuestas, payloads ni intentos anteriores. Las convocatorias completas del
programa anterior se adoptan una sola vez. Las demás reutilizan sus consultas
correctas y pasan a la planificación por fases.

## Validación

```sh
python3 -m unittest discover -s tests -v
```

Las pruebas usan respuestas sintéticas, sin descargas electorales. Cubren el
orden de fases, paralelismo dentro de un municipio grande, cola limitada,
coalescencia de consultas, reanudación, migración del esquema anterior, hashes,
recuperación de catálogos, exportaciones interrumpidas y pausas HTTP.
