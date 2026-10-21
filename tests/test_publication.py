import csv
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/package_datasets.py'
spec = importlib.util.spec_from_file_location('package_datasets', SCRIPT)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class PublicationTests(unittest.TestCase):
    def test_metadata_sanitization_preserves_input(self):
        source = {'database': '/private/server/archive.sqlite3', 'data_complete': False}
        clean = publication.public_manifest(source)
        self.assertNotIn('database', clean)
        self.assertIn('database', source)
        self.assertFalse(clean['data_complete'])

    def test_packages_exclude_operations_and_preserve_raw_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / 'snapshot'
            snapshot.mkdir()
            dates = list(publication.DATES)
            for date in dates:
                folder = snapshot / f'elecciones/{date}'
                folder.mkdir(parents=True)
                with gzip.open(folder / f'andalucia_t5_{date}_parcial.csv.gz', 'wt', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=['tipo_registro', 'estado_calidad'])
                    writer.writeheader()
                    writer.writerow({'tipo_registro': 'mesa', 'estado_calidad': 'incompleto'})
                (folder / 'mesas.ndjson.gz').write_bytes(gzip.compress(b'{"votes":null}\n'))
                (folder / 'server.log.gz').write_bytes(b'private operational content')
                (folder / 'manifest.json').write_text(json.dumps({'mesas_catalogadas': 1, 'source_unavailable': 1,
                                                                  'database': '/private/archive.sqlite3'}))
            for name in ['mesas-pendientes.csv', 'otras-incidencias-calidad.json', 'contextos-mesas.json',
                         'villamanrique-1990.json', 'contraste-boletines.json']:
                (snapshot / name).write_text('[]')
            (snapshot / 'estado_registros.csv.gz').write_bytes(gzip.compress(b'state\n'))
            (snapshot / 'solicitud-actas-preparada.md').write_text('private correspondence draft')
            (snapshot / 'manifest.json').write_text(json.dumps({'tconvocatoria': 5, 'elections': dates,
                                                                'files': [], 'original_quality_counts': {'mesa/incompleto': 13}}))
            output = root / 'release'
            publication.package(snapshot, output, 'test-v1')
            self.assertEqual(len(list(output.glob('*.zip'))), 14)
            with zipfile.ZipFile(output / f'parlamento-andalucia-{dates[0]}.zip') as archive:
                self.assertNotIn('server.log.gz', archive.namelist())
                self.assertNotIn('database', json.loads(archive.read('manifest.json')))
                self.assertEqual(archive.read('mesas.ndjson.gz'), (snapshot / f'elecciones/{dates[0]}/mesas.ndjson.gz').read_bytes())
            with zipfile.ZipFile(output / 'parlamento-andalucia-1982-2026.zip') as archive:
                self.assertNotIn('solicitud-actas-preparada.md', archive.namelist())
            catalog = json.loads((output / 'catalogo.json').read_text())
            self.assertEqual(catalog['elections'][0]['quality']['incompleto'], 1)

    def test_rejects_non_parliament_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'manifest.json').write_text(json.dumps({'tconvocatoria': 1, 'elections': []}))
            with self.assertRaises(ValueError):
                publication.package(path, path / 'out', 'v1')


if __name__ == '__main__':
    unittest.main()
