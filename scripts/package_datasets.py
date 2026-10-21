#!/usr/bin/env python3
"""Package a verified Parliament snapshot for public, versioned downloads.

No network requests; raw gzip files are copied byte for byte. Operational files,
draft correspondence, the SQLite database and referendum directories are excluded.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

REPO = 'https://github.com/jesusmgodoy/andalucia-siel-api'
SOURCE = 'https://resultadoseleccionesandalucia.es/'
LEGAL = SOURCE + 'aviso-legal.html'
DATA_FILES = {'mesas_largo.csv.gz', 'cera.ndjson.gz', 'respuestas.ndjson.gz',
              'escrutinios_largo.csv.gz', 'mesas.ndjson.gz', 'cera_largo.csv.gz',
              'resumenes.csv.gz', 'mesas_catalogo.csv.gz', 'incidencias_origen.json'}
DATES = {198205: '23 de mayo de 1982', 198606: '22 de junio de 1986',
         199006: '23 de junio de 1990', 199406: '12 de junio de 1994',
         199603: '3 de marzo de 1996', 200003: '12 de marzo de 2000',
         200403: '14 de marzo de 2004', 200803: '9 de marzo de 2008',
         201203: '25 de marzo de 2012', 201503: '22 de marzo de 2015',
         201812: '2 de diciembre de 2018', 202206: '19 de junio de 2022',
         202605: '17 de mayo de 2026'}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def public_manifest(original):
    result = dict(original)
    # This is publication metadata, not an API response. Never publish a VPS path.
    result.pop('database', None)
    result['publication_note'] = 'Metadatos de publicación sin ruta local de SQLite. Los archivos gzip de la fuente se conservan sin modificación.'
    return result


def package(snapshot, output, version):
    source_manifest = json.loads((snapshot / 'manifest.json').read_text())
    if source_manifest['tconvocatoria'] != 5 or len(source_manifest['elections']) != 13:
        raise ValueError('Se requiere una copia verificada de las 13 elecciones al Parlamento')
    if not version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._' for c in version):
        raise ValueError('Identificador de versión no válido')
    if output.exists():
        raise FileExistsError(f'La carpeta de publicación ya existe: {output}')
    # Verify the frozen source before building anything for publication.
    for item in source_manifest['files']:
        path = snapshot / item['file']
        if not path.resolve().is_relative_to(snapshot.resolve()) or sha256(path) != item['sha256']:
            raise ValueError(f'La copia de origen no supera la verificación: {item["file"]}')
    output.mkdir(parents=True)
    stage = output / 'contenido'
    stage.mkdir()
    reuse = f'''# Fuentes y reutilización

Información obtenida del Portal de la Junta de Andalucía.

Fuente de resultados: SIEL, Junta de Andalucía ({SOURCE}). Edición independiente
preparada mediante andalucia-siel-api ({REPO}); no es una publicación oficial ni
se presenta como respaldada por la Junta de Andalucía. No se utilizan sus logotipos.

Fecha de esta edición: 21 de octubre de 2026. Las fechas individuales de consulta
se conservan en los registros. El aviso de origen ({LEGAL}) indica CC BY 3.0 para
los textos del portal y exige reconocer la fuente y no desnaturalizar la información.
Se mantienen esas condiciones para los contenidos de origen a los que correspondan;
esta edición no atribuye derechos exclusivos sobre los hechos electorales ni
pretende extender esa licencia al código del programa.

Al reutilizar, conserve la atribución, indique la versión y describa sus cambios.
La información sobre incidencias es parte de la documentación del conjunto.
Las denominaciones literales de candidaturas y territorios se conservan en los datos.
'''
    guide = f'''# Elecciones al Parlamento de Andalucía, 1982–2026

Versión: {version}. Edición de datos: 21 de octubre de 2026.

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

Código y metodología: {REPO}. Fuente: {SOURCE}.
Consulte `REUTILIZACION.md` y `CALIDAD.md` antes de analizar o redistribuir.
'''
    quality = '''# Calidad y límites de la edición de 21 de octubre de 2026

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
'''
    for name, value in [('LEEME.md', guide), ('REUTILIZACION.md', reuse), ('CALIDAD.md', quality)]:
        (stage / name).write_text(value, encoding='utf-8')
        shutil.copy2(stage / name, output / name)
    for name in ['estado_registros.csv.gz', 'mesas-pendientes.csv', 'otras-incidencias-calidad.json',
                 'contextos-mesas.json', 'villamanrique-1990.json', 'contraste-boletines.json']:
        shutil.copy2(snapshot / name, stage / name)
    entries = []
    for date in sorted(source_manifest['elections'], reverse=True):
        source = snapshot / f'elecciones/{date}'
        dest = stage / f'elecciones/{date}'
        dest.mkdir(parents=True)
        for path in source.iterdir():
            if path.name in DATA_FILES or (path.name.startswith(f'andalucia_t5_{date}_') and path.name.endswith('.csv.gz')):
                shutil.copy2(path, dest / path.name)
        original = json.loads((source / 'manifest.json').read_text())
        (dest / 'manifest.json').write_text(json.dumps(public_manifest(original), ensure_ascii=False, indent=2) + '\n')
        quality_counts = collections.Counter()
        combined = next(dest.glob('andalucia_*.csv.gz'))
        with gzip.open(combined, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['tipo_registro'] == 'mesa':
                    quality_counts[row['estado_calidad']] += 1
        name = f'parlamento-andalucia-{date}.zip'
        with zipfile.ZipFile(output / name, 'w', compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(dest.iterdir()):
                archive.write(path, path.name)
            for document in ['LEEME.md', 'CALIDAD.md', 'REUTILIZACION.md']:
                archive.write(stage / document, document)
        entries.append({'date': date, 'label': DATES[date], 'year': int(str(date)[:4]),
                        'tables': original['mesas_catalogadas'], 'quality': dict(quality_counts),
                        'failed_queries': original['source_unavailable'], 'filename': name,
                        'bytes': (output / name).stat().st_size, 'sha256': sha256(output / name),
                        'url': f'{REPO}/releases/download/{version}/{name}'})
    all_name = 'parlamento-andalucia-1982-2026.zip'
    with zipfile.ZipFile(output / all_name, 'w', compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                archive.write(path, str(path.relative_to(stage)))
    catalog = {'version': version, 'edition': '2026-10-21', 'scope': 'Parlamento de Andalucía',
               'source': SOURCE, 'source_legal': LEGAL, 'release_url': f'{REPO}/releases/tag/{version}',
               'all': {'filename': all_name, 'bytes': (output / all_name).stat().st_size,
                       'sha256': sha256(output / all_name), 'url': f'{REPO}/releases/download/{version}/{all_name}'},
               'elections': entries, 'table_quality': source_manifest['original_quality_counts']}
    (output / 'catalogo.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
    assets = [path for path in sorted(output.iterdir()) if path.is_file()]
    for path in assets:
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None or any(n.startswith('/') or '..' in Path(n).parts for n in archive.namelist()):
                    raise ValueError(f'ZIP no válido: {path.name}')
    sums = ''.join(f'{sha256(path)}  {path.name}\n' for path in assets)
    (output / 'SHA256SUMS.txt').write_text(sums)
    assets.append(output / 'SHA256SUMS.txt')
    (output / 'upload-manifest.json').write_text(json.dumps([
        {'name': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)} for path in assets], indent=2) + '\n')
    print(json.dumps({'elections': len(entries), 'assets': len(assets), 'all_bytes': catalog['all']['bytes'],
                      'verified_zip_files': 14, 'output': str(output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    package(args.snapshot, args.output, args.version)
