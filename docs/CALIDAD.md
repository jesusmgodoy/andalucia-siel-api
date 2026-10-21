# Calidad y límites de la edición de 21 de octubre de 2026

El archivo conserva 114.944 entradas de mesa de 13 elecciones al Parlamento:
111.878 pasan las comprobaciones del cliente, 3.017 son inconsistentes y 49 son
incompletas. CERA provincial: 96 registros disponibles y ocho incompletos de 1982.

- 41 mesas no tienen escrutinio válido: 32 de 1986, una de 1990, dos de 2015,
  dos de 2018 y cuatro de 2022. Sus resúmenes declaran cero votos con censo
  positivo; eso no acredita abstención total. Los votos ausentes no se imputan.
- Las otras ocho mesas incompletas responden, pero tienen abstención negativa:
  siete de 1982 y una de 2004. Se conservan sus cifras y advertencias.
- Las 3.017 inconsistencias son diferencias entre suma de candidaturas y total
  declarado: 2.811 de 1996, 205 de 1990 y una de 2018. No se elige arbitrariamente
  cuál de las cifras es correcta.
- Villamanrique de la Condesa, 1990: las tres mesas con escrutinio suman el
  resultado municipal por candidatura, censo y votantes. El catálogo contiene una
  cuarta entrada con 711 electores y cero votos. Se considera probable anomalía
  de catálogo, sin certificación externa; el registro original se conserva.
- Las relaciones oficiales de mesas previstas de 2015, 2018 y 2022 confirman los
  identificadores de ocho mesas pendientes. No acreditan sus votos efectivos.

No todos los errores HTTP representan mesas perdidas: el catálogo municipal es
global y contiene códigos sin resultados independientes en todas las fechas.
Los fallos de distribuciones por partido tampoco equivalen necesariamente a
votos únicos ausentes, pues pueden existir en los escrutinios municipales.
Los agregados del propio SIEL no siempre concilian entre sí. No se certifica
integridad histórica ni se recomienda sumar mesas para sustituir los totales
oficiales sin comprobar esas diferencias.

En la descarga conjunta, `estado_registros.csv.gz` conserva los indicadores de
calidad de todos los registros. `mesas-pendientes.csv` lista las 41 sin escrutinio;
`otras-incidencias-calidad.json` identifica las ocho adicionales y los recuentos.
El resto de incidencias de cada elección permanece en sus manifiestos originales.
La fecha de cierre de una descarga no equivale a que los datos estén completos.

Fuentes de contraste:
- https://www.dipusevilla.es/export/bop/201502/02.pdf (páginas 29–30).
- https://www.dipusevilla.es/system/modules/com.saga.sagasuite.theme.diputacion.sevilla.corporativo/handlers/download-bop.pdf?id=db2786d5-cd48-11e8-9d7e-0050569fe27b (páginas 5 y 29).
- https://www.dipusevilla.es/system/modules/com.saga.sagasuite.theme.diputacion.sevilla.corporativo/handlers/download-bop.pdf?id=1956442e-c7b3-11ec-a4b1-0050569fe27b (páginas 9, 17 y 18).
