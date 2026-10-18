# Casos reales de calidad del SIEL

`quality_cases.json` conserva resúmenes y escrutinios consultados el 18 de octubre
de 2026 en `https://ws040.juntadeandalucia.es/siel-api`. Las cifras no se han
corregido. Los parámetros de cada respuesta están en `source.params`.

Incluye las discrepancias de candidaturas de 1990 (Andalucía y Sevilla), tres
mesas de 1996 y la discrepancia de votantes de 2018 (Andalucía y Córdoba), además
de una mesa coherente de 2026. Las anomalías se reconsultaron en la auditoría:
persistían los resúmenes y los votos por candidatura, aunque podía cambiar el
orden de candidaturas empatadas.

Los endpoints son `/v1/resumen/{ambito}` y
`/v1/escrutinio/ambito/{ambito}`. En los registros de mesa se conservan también
las URLs de origen. Estos casos son pruebas pequeñas, no un conjunto exhaustivo
de resultados ni de incidencias.

`archive_api_schema.json` conserva únicamente rutas y parámetros de la
especificación SIEL consultada el 18-10-2026. Permite probar la normalización de
consultas del archivo exhaustivo sin acceder a la red. Los resultados de
`test_archive.py` son sintéticos; no representan votaciones reales.
