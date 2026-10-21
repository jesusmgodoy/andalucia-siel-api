"""Reconcile archived catalogues without inventing, deleting or replacing votes."""
from __future__ import annotations

from collections import Counter
import json
from typing import Callable


def reconcile_coverage(db, result: Callable, t: int, f: int, references: dict) -> dict:
    counts = Counter()
    municipal_counts = Counter()
    for row in db.execute("SELECT params FROM nodes WHERE t=? AND f=? AND level='mesa'", (t, f)):
        params = json.loads(row['params'])
        counts[str(params['provincia'])] += 1
        municipal_counts[(params['provincia'], params['municipio'])] += 1
    enumerated = sum(counts.values())
    summary_row = db.execute("SELECT * FROM responses WHERE t=? AND f=? AND path='/v1/resumen/cautonoma'", (t, f)).fetchone()
    summary = result(summary_row) if summary_row else None
    expected = summary.get('nummesas') if isinstance(summary, dict) else None
    branches = db.execute('SELECT COUNT(*) FROM branches WHERE t=? AND f=?', (t, f)).fetchone()[0]
    municipal_sum = 0
    mismatches = []
    for row in db.execute("SELECT * FROM responses WHERE t=? AND f=? AND path='/v1/resumen/municipio' AND ok=1", (t, f)):
        params = json.loads(row['params'])
        body = result(row)
        n = body.get('nummesas') if isinstance(body, dict) else None
        if not isinstance(n, int) or isinstance(n, bool):
            continue
        municipal_sum += n
        actual = municipal_counts[(params['provincia'], params['municipio'])]
        if actual != n:
            mismatches.append({'provincia': params['provincia'], 'municipio': params['municipio'],
                               'aggregate': n, 'catalog': actual})
    reference = references.get(f'{t}/{f}')
    reference_match = False
    if reference:
        provinces = {str(k): v for k, v in reference['provinces'].items()}
        reference_match = (reference['total'] == sum(provinces.values()) == enumerated
                           and dict(counts) == provinces)
    aggregate_match = isinstance(expected, int) and not isinstance(expected, bool) and expected == enumerated
    complete = enumerated > 0 and branches == 0 and not mismatches and (reference_match if reference else aggregate_match)
    return {
        'catalog_coverage_complete': complete,
        'basis': 'official_physical_tables' if reference_match and complete else
                 'api_aggregate' if complete else 'not_verified',
        'catalog_count': enumerated, 'aggregate_count': expected,
        'municipal_aggregate_sum': municipal_sum,
        'municipal_mismatches': mismatches,
        'province_catalog_counts': dict(counts),
        'official_reference': reference,
        'official_reference_matches': reference_match if reference else None,
        'table_detail_unavailable': enumerated == 0 and isinstance(expected, int) and expected > 0,
        'note': 'La referencia física acredita recuentos, no la exactitud de los votos. No se supone que una diferencia de ocho sea CERA.'
    }


def failure_report(db, result: Callable, identity: Callable, t=None, f=None) -> dict:
    where, args = (' AND t=? AND f=?', (t, f)) if t is not None else ('', ())
    categories = Counter()
    endpoints = Counter()
    details = []
    rows = db.execute('SELECT * FROM responses WHERE ok=0' + where + ' ORDER BY t,f,path,key', args).fetchall()
    for row in rows:
        path, params = row['path'], json.loads(row['params'])
        category = 'error_http_origen'
        reason = row['error']
        if '/municipio' in path and path.startswith(('/v1/resumen/', '/v1/escrutinio/ambito/')):
            key = identity('/v1/opciones/distrito', params)[0]
            catalog = db.execute('SELECT * FROM responses WHERE key=?', (key,)).fetchone()
            if catalog and catalog['ok'] and result(catalog) == []:
                category = 'municipio_sin_desglose_en_api'
                reason = 'La consulta municipal falla y el catálogo de distritos está vacío. No demuestra pérdida de mesas ni que el municipio no existiera.'
        elif path == '/v1/escrutinio/ambito/mesa':
            key = identity('/v1/resumen/mesa', params)[0]
            summary_row = db.execute('SELECT * FROM responses WHERE key=?', (key,)).fetchone()
            summary = result(summary_row) if summary_row and summary_row['ok'] else None
            if isinstance(summary, dict) and summary.get('votostotales') == 0 and summary.get('votoscandidatura') == 0:
                category = 'resumen_cero_sin_escrutinio'
                reason = 'El resumen declara cero votos, pero falta el escrutinio; no se valida una abstención total ni se imputan ceros por candidatura.'
        elif row['status'] is None:
            category = 'timeout' if 'Timeout' in (row['error'] or '') else 'error_red'
        elif row['status'] == 404:
            category = 'endpoint_no_disponible'
        categories[category] += 1
        endpoints[path] += 1
        details.append({'request_id': row['key'], 't': row['t'], 'f': row['f'], 'endpoint': path,
                        'params': params, 'status': row['status'], 'category': category,
                        'reason': reason, 'source_error': row['error']})
    return {'failed_queries': len(rows), 'by_category': dict(categories),
            'by_endpoint': dict(endpoints), 'details': details,
            'note': 'Las categorías no borran errores del origen ni convierten ausencias en respuestas válidas.'}
