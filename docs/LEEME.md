# Elecciones al Parlamento de Andalucía, 1982–2026

Versión: datos-2026-10-21-v1. Edición de datos: 21 de octubre de 2026.

13 convocatorias. Datos SIEL conservados con sus incidencias. No se incluyen
referendos. Descarga por elección o conjunta; el ZIP conjunto contiene las mismas
13 carpetas, no una versión filtrada ni corregida del conjunto.

## Por dónde empezar

1. Descomprima el ZIP. Los CSV interiores siguen comprimidos en gzip (`.csv.gz`).
2. El CSV `andalucia_t5_...csv.gz` reúne mesas y CERA provincial. `tipo_registro`
   distingue ambos; `fconvocatoria` identifica el año y mes.
3. Revise `estado_calidad`: `ok`, `inconsistente` o `incompleto`.
   `ok` significa que pasó las comprobaciones del cliente, no un cotejo con actas.
4. No convierta celdas vacías en cero. Para un subconjunto sin incidencias detectadas,
   filtre `estado_calidad=ok` y documente las exclusiones y sus posibles efectos.

El sufijo heredado `_completo` de algunos CSV acredita el criterio de cobertura
del catálogo usado por el exportador; no certifica todos los votos. Lea la calidad.

## Contenido de cada convocatoria

- `andalucia_t5_...csv.gz`: una fila por mesa o registro CERA provincial, votos en columnas.
- `mesas_largo.csv.gz`: resultados de mesas en formato largo, una fila por candidatura.
- `cera_largo.csv.gz`: resultados CERA en formato largo.
- `resumenes.csv.gz` y `escrutinios_largo.csv.gz`: agregados y resúmenes disponibles.
- `mesas_catalogo.csv.gz`: identificadores y contexto de las mesas enumeradas.
- `mesas.ndjson.gz` y `cera.ndjson.gz`: registros estructurados con datos y errores.
- `respuestas.ndjson.gz`: respuestas de la API con procedencia y metadatos.
- `manifest.json`, `incidencias_origen.json`: recuentos, cobertura e incidencias HTTP.
- `LEEME.md`, `CALIDAD.md`, `REUTILIZACION.md`: guía, limitaciones y procedencia.

No se distribuyen la base SQLite, registros de administración de servidores ni
borradores de solicitudes. Los gzip coinciden byte por byte con la copia verificada.
Solo se retira la ruta local de SQLite de los metadatos de publicación.

## Variables principales

- Identificadores: `tconvocatoria`, `fconvocatoria`, `provincia_clave`,
  `municipio_clave`, `distrito_clave`, `seccion_valor`, `mesa_valor`.
  Mantenga sección y mesa como texto para conservar ceros iniciales y letras.
- Recuentos: `censo`, `votantes`, `abstenciones`, `votos_nulos`, `votos_validos`,
  `votos_blanco`, `votos_candidaturas`; las restantes columnas de candidatura
  conservan las denominaciones de origen.
- Calidad: `estado_descarga`, `estado_calidad`, `incidencias_calidad`.
- Los CSV largos incorporan candidatura y número de votos por fila; no sume
  columnas repetidas de censo o votantes entre candidaturas.

Código y metodología: https://github.com/jesusmgodoy/andalucia-siel-api. Fuente: https://resultadoseleccionesandalucia.es/.
Consulte `REUTILIZACION.md` y `CALIDAD.md` antes de analizar o redistribuir.
