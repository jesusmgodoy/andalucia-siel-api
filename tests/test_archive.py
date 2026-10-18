import csv
import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
from unittest.mock import patch
import requests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('arch', ROOT / 'scripts/archive_siel.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
DOC = json.loads((ROOT / 'tests/fixtures/archive_api_schema.json').read_text())

class FakeSession:

    def __init__(self, failed=False):
        self.calls = []
        self.failed = failed

    def get(self, url, timeout=None):
        u = urlsplit(url)
        path = u.path.removeprefix('/siel-api')
        p = dict(parse_qsl(u.query))
        self.calls.append((path, p))
        code = 200
        if path == '/api-docs':
            data = DOC
        elif path == '/v1/opciones/tconvocatoria':
            data = [{'clave': 1, 'valor': 'Referéndum'}, {'clave': 5, 'valor': 'Elecciones Autonómicas'}]
        elif path == '/v1/opciones/fconvocatoria':
            data = [{'clave': 202605 if p['tconvocatoria'] == '5' else 200702, 'valor': 'fecha'}]
        elif path == '/v1/opciones/cautonoma':
            data = [{'clave': 1, 'valor': 'Andalucía'}]
        elif path == '/v1/opciones/provincia':
            data = [{'clave': n, 'valor': str(n)} for n in [4, 11, 14, 18, 21, 23, 29, 41]]
        elif path == '/v1/opciones/municipio':
            data = [{'clave': 1, 'valor': 'Municipio'}]
        elif path == '/v1/opciones/distrito':
            data = [{'clave': 1, 'valor': 'Distrito'}]
            if self.failed and p['tconvocatoria'] == '1' and (p['provincia'] == '4'):
                code = 500
                data = {'error': 'source error'}
        elif path == '/v1/opciones/seccion':
            data = [{'clave': 1, 'valor': '0001'}]
        elif path == '/v1/opciones/mesa':
            data = [{'clave': 1, 'valor': 'A'}]
        elif '/opciones/partido/' in path:
            data = [{'clave': 10, 'valor': 'Candidatura'}]
        elif path == '/v1/celectos':
            data = []
        else:
            identity = {k: {'clave': int(v) if k not in ['seccion', 'mesa'] else 1, 'valor': v if k in ['seccion', 'mesa'] else str(v)} for k, v in p.items()}
            factor = 8 if path.endswith('cautonoma') else 1
            if '/rausentes/' in path:
                factor = 0
            if '/resumen/' in path:
                data = {'idescrutinio': identity, 'censo': 10 * factor, 'votostotales': 6 * factor, 'abstenciones': 4 * factor, 'votosvalidos': 5 * factor, 'votosnulos': factor, 'votosblanco': factor, 'votoscandidatura': 4 * factor, 'nummesas': 8 if path.endswith('cautonoma') else 1}
            else:
                data = {'idescrutinio': identity, 'votos': [{'conjunto': 'A', 'numvotos': 3 * factor}, {'conjunto': 'B', 'numvotos': factor}]}
        r = requests.Response()
        r.status_code = code
        r._content = json.dumps(data, ensure_ascii=False).encode()
        r.headers['Content-Type'] = 'application/json'
        return r

class Tests(unittest.TestCase):

    def test_archive_resume_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeSession()
            store = a.Archive(Path(td), workers=2, rps=100000, reserve_gib=1, max_attempts=1)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            calls = len(fake.calls)
            self.assertTrue((Path(td) / 'finished.json').exists())
            self.assertEqual({path for path, _ in fake.calls if path != '/api-docs'}, {path for path, methods in DOC['paths'].items() if 'get' in methods})
            for t, f in [(5, 202605), (1, 200702)]:
                folder = Path(td) / f't{t}' / str(f)
                m = json.loads((folder / 'manifest.json').read_text())
                self.assertTrue(m['catalog_coverage_complete'])
                self.assertEqual(m['mesas_catalogadas'], 8)
                csvfile = next(folder.glob('*_completo.csv.gz'))
                with gzip.open(csvfile, 'rt') as h:
                    rows = list(csv.DictReader(h))
                self.assertEqual(len(rows), 16)
                self.assertTrue(all((r['estado_calidad'] == 'ok' for r in rows)))
            with patch.object(store, 'session', return_value=fake):
                store.run()
            self.assertEqual(len(fake.calls), calls)
            r = store.row('/v1/resumen/mesa', {'cautonoma': 1, 'tconvocatoria': 5, 'fconvocatoria': 202605, 'provincia': 4, 'municipio': 1, 'distrito': 1, 'seccion': '0001', 'mesa': 'A'})
            self.assertEqual(a.hashlib.sha256(store.body(r)).hexdigest(), r['hash'])
            self.assertTrue(all((p.get('tconvocatoria') in (None, '1', '5') for _, p in fake.calls)))
            store.db.close()

    def test_catalog_failure_is_explicit_and_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeSession(failed=True)
            store = a.Archive(Path(td), workers=2, rps=100000, reserve_gib=1, max_attempts=1)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            m = json.loads((Path(td) / 't1/200702/manifest.json').read_text())
            self.assertFalse(m['catalog_coverage_complete'])
            self.assertEqual(m['mesas_catalogadas'], 7)
            self.assertEqual(m['unavailable_catalog_branches'], 1)
            self.assertTrue(next((Path(td) / 't1/200702').glob('*_parcial.csv.gz')))
            self.assertGreater(m['source_unavailable'], 0)
            store.db.close()

    def test_disk_reserve_stops_before_requests(self):
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(Path(td), reserve_gib=100000)
            with self.assertRaises(a.DiskReserveError):
                store.disk_check()
            store.db.close()

class SchedulingTests(unittest.TestCase):

    def make(self, td, **kwargs):
        return a.Archive(Path(td), workers=kwargs.pop('workers', 4), rps=100000, reserve_gib=1, **kwargs)

    def test_all_core_elections_and_exports_precede_distribution_views(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeSession()
            store = self.make(td, max_attempts=1)
            actual = store.download_distributions

            def distributions(t, f):
                for et, ef in [(5, 202605), (1, 200702)]:
                    m = json.loads((Path(td) / f't{et}/{ef}/manifest.json').read_text())
                    self.assertEqual(m['stage'], 'core')
                    self.assertFalse(m['archive_finished'])
                    self.assertTrue(m['mesa_data_complete'])
                return actual(t, f)
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'download_distributions', side_effect=distributions):
                store.run()
            last_mesa = max((i for i, (path, _) in enumerate(fake.calls) if path.endswith('/mesa')))
            first_distribution = min((i for i, (path, _) in enumerate(fake.calls) if path.startswith('/v1/escrutinio/partido/')))
            self.assertGreater(first_distribution, last_mesa)
            self.assertLessEqual(store.max_pending_observed, store.workers * 2)
            store.db.close()

    def test_large_single_municipality_uses_several_workers(self):
        import threading, time

        class SingleTown(FakeSession):

            def __init__(self):
                super().__init__()
                self.active = 0
                self.peak = 0
                self.lock = threading.Lock()

            def get(self, url, timeout=None):
                response = super().get(url, timeout)
                path = urlsplit(url).path
                p = dict(parse_qsl(urlsplit(url).query))
                if path.endswith('/opciones/municipio') and p['provincia'] != '4':
                    response._content = b'[]'
                if path.endswith('/opciones/mesa'):
                    response._content = json.dumps([{'clave': i, 'valor': str(i)} for i in range(12)]).encode()
                if '/resumen/mesa' in path or '/ambito/mesa' in path:
                    with self.lock:
                        self.active += 1
                        self.peak = max(self.peak, self.active)
                    time.sleep(0.01)
                    with self.lock:
                        self.active -= 1
                return response
        with tempfile.TemporaryDirectory() as td:
            fake = SingleTown()
            store = self.make(td, max_attempts=1)
            store.paths = {p: m['get'] for p, m in DOC['paths'].items() if 'get' in m}
            provinces = [{'clave': n, 'valor': str(n)} for n in [4, 11, 14, 18, 21, 23, 29, 41]]
            with patch.object(store, 'session', return_value=fake):
                store.download_core(5, 202605, provinces)
            self.assertEqual(store.totals()['mesas_completed'], 12)
            self.assertGreaterEqual(fake.peak, 3)
            self.assertLessEqual(fake.peak, 4)
            self.assertLessEqual(store.max_pending_observed, 8)
            store.db.close()

    def test_retry_pass_recovers_catalog_and_discovers_missing_tables(self):

        class Once(FakeSession):

            def __init__(self):
                super().__init__(failed=True)
                self.failures = 0

            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                if r.status_code == 500:
                    self.failures += 1
                    if self.failures >= 1:
                        self.failed = False
                return r
        with tempfile.TemporaryDirectory() as td:
            fake = Once()
            store = self.make(td, max_attempts=2)
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0):
                store.run()
            m = json.loads((Path(td) / 't1/200702/manifest.json').read_text())
            self.assertTrue(m['catalog_coverage_complete'])
            self.assertEqual(m['mesas_completed'], 8)
            self.assertEqual(m['unavailable_catalog_branches'], 0)
            self.assertEqual(m['source_unavailable'], 0)
            failed_i = [i for i, (path, p) in enumerate(fake.calls) if path.endswith('/opciones/distrito') and p['tconvocatoria'] == '1' and (p['provincia'] == '4')]
            self.assertEqual(len(failed_i), 2)
            self.assertGreater(failed_i[-1], max((i for i, (path, _) in enumerate(fake.calls[:failed_i[-1]]) if '/escrutinio/partido/' in path)))
            counts = {}
            for path, p in fake.calls:
                key = (path, a.canonical(p))
                counts[key] = counts.get(key, 0) + 1
            self.assertEqual(sum((n > 1 for n in counts.values())), 1)
            store.db.close()

    def test_resume_after_interrupted_core_never_refetches_saved_success(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeSession()
            store = self.make(td, max_attempts=1)
            original = store.download_distributions

            def interrupt(*_):
                raise a.StopRequested()
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'download_distributions', side_effect=interrupt):
                with self.assertRaises(a.StopRequested):
                    store.run()
            saved = list(fake.calls)
            store.db.close()
            store = self.make(td, max_attempts=1)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            new = fake.calls[len(saved):]
            self.assertTrue(new)
            self.assertFalse(any((path.endswith('/mesa') for path, _ in new)))
            self.assertEqual(store.totals()['mesas_completed'], 16)
            store.db.close()

    def test_original_vps_schema_migration_preserves_hash_and_attempt_history(self):
        import sqlite3, zlib, hashlib
        with tempfile.TemporaryDirectory() as td:
            db = sqlite3.connect(Path(td) / 'archivo.sqlite3')
            db.executescript('CREATE TABLE responses(key TEXT PRIMARY KEY,path TEXT NOT NULL,params TEXT NOT NULL,t INTEGER,f INTEGER,status INTEGER,ok INTEGER NOT NULL,attempts INTEGER NOT NULL,fetched_at TEXT,url TEXT,hash TEXT,error TEXT,headers TEXT);\n    CREATE TABLE attempts(id INTEGER PRIMARY KEY,key TEXT,fetched_at TEXT,status INTEGER,hash TEXT,error TEXT);\n    CREATE TABLE payloads(hash TEXT PRIMARY KEY,body BLOB NOT NULL);')
            body = b'{ "source": true, "exact_bytes": "retained" }'
            digest = hashlib.sha256(body).hexdigest()
            path = '/v1/resumen/mesa'
            params = {'cautonoma': 1, 'tconvocatoria': 5, 'fconvocatoria': 202605, 'provincia': 4, 'municipio': 1, 'distrito': 1, 'seccion': '0001', 'mesa': 'A'}
            key = hashlib.sha256((path + '?' + a.canonical(params)).encode()).hexdigest()
            db.execute('INSERT INTO payloads VALUES(?,?)', (digest, zlib.compress(body)))
            db.execute('INSERT INTO responses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (key, path, a.canonical(params), 5, 202605, 200, 1, 1, a.now(), 'source', digest, None, '{}'))
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)', (1, key, a.now(), 200, digest, None))
            db.commit()
            db.close()
            store = self.make(td, max_attempts=1)
            with patch.object(store, 'session') as session:
                self.assertEqual(store.fetch(path, params), json.loads(body))
                session.assert_not_called()
            self.assertEqual(store.body(store.row(path, params)), body)
            self.assertEqual(store.db.execute('SELECT count(*) FROM attempts').fetchone()[0], 1)
            self.assertIn('duration_ms', [r[1] for r in store.db.execute('PRAGMA table_info(attempts)')])
            store.db.close()

    def test_concurrent_duplicate_request_is_coalesced(self):
        import concurrent.futures
        with tempfile.TemporaryDirectory() as td:
            store = self.make(td, max_attempts=1)
            fake = FakeSession()
            with patch.object(store, 'session', return_value=fake), concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: store.fetch('/test'), range(16)))
            self.assertEqual(len(fake.calls), 1)
            self.assertTrue(all((r == results[0] for r in results)))
            store.db.close()

    def test_retry_after_applies_on_first_failure_and_does_not_hold_worker(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            store = self.make(td, max_attempts=3)
            r = requests.Response()
            r.status_code = 429
            r._content = b'{"error":"busy"}'
            r.headers['Retry-After'] = '19'
            session = unittest.mock.Mock()
            session.get.return_value = r
            started = time.monotonic()
            with patch.object(store, 'session', return_value=session):
                self.assertIsNone(store.fetch('/test'))
            self.assertGreaterEqual(store.next_request, started + 19)
            row = store.row('/test', {})
            self.assertEqual(row['attempts'], 1)
            self.assertGreater(row['next_retry_at'], time.time() + 18)
            self.assertEqual(store.in_flight, {})
            store.db.close()

    def test_refresh_discovers_new_election_without_refetching_old_tables(self):

        class NewElection(FakeSession):

            def __init__(self):
                super().__init__()
                self.extra = False

            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                p = dict(parse_qsl(urlsplit(url).query))
                if self.extra and urlsplit(url).path.endswith('/opciones/fconvocatoria') and (p['tconvocatoria'] == '5'):
                    r._content = json.dumps([{'clave': 202605, 'valor': 'original'}, {'clave': 203005, 'valor': 'nueva'}]).encode()
                return r
        with tempfile.TemporaryDirectory() as td:
            fake = NewElection()
            store = self.make(td, max_attempts=1)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            n = len(fake.calls)
            fake.extra = True
            with patch.object(store, 'session', return_value=fake):
                store.run(refresh_catalogs=True)
            self.assertTrue((Path(td) / 't5/203005/manifest.json').exists())
            new = fake.calls[n:]
            self.assertTrue(any((p.get('fconvocatoria') == '203005' for _, p in new)))
            self.assertFalse(any((path.endswith('/mesa') and p.get('fconvocatoria') == '202605' for path, p in new)))
            store.db.close()

    def test_export_failure_keeps_published_files_and_has_no_completion_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make(td, max_attempts=1)
            fake = FakeSession()
            with patch.object(store, 'session', return_value=fake):
                store.run()
            path = Path(td) / 't5/202605/mesas.ndjson.gz'
            original = path.read_bytes()
            store.db.execute("DELETE FROM phases WHERE phase='final_export'")
            store.db.commit()
            with patch.object(store, 'export_tabular', side_effect=RuntimeError('disk write interrupted')):
                with self.assertRaises(RuntimeError):
                    store.export_election(5, 202605, [])
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(store.phase_done(5, 202605, 'final_export'))
            store.db.close()

    def test_stop_prevents_new_network_calls(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.make(td)
            store.stop.set()
            with patch.object(store, 'session') as session:
                with self.assertRaises(a.StopRequested):
                    store.fetch('/test')
                session.assert_not_called()
            store.db.close()

class RecoveryTests(unittest.TestCase):

    def test_permanent_error_only_retried_when_explicitly_requested(self):

        class Missing(FakeSession):

            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                if urlsplit(url).path.endswith('/celectos'):
                    r.status_code = 404
                    r._content = b'{"error":"missing"}'
                return r
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=2, rps=100000, reserve_gib=1, max_attempts=3)
            fake = Missing()
            with patch.object(store, 'session', return_value=fake):
                store.run()
            first = sum((path == '/v1/celectos' for path, _ in fake.calls))
            self.assertEqual(first, 2)
            n = len(fake.calls)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            self.assertEqual(len(fake.calls), n)
            with patch.object(store, 'session', return_value=fake):
                store.run(retry_unavailable=True)
            self.assertEqual(sum((path == '/v1/celectos' for path, _ in fake.calls)), 4)
            self.assertFalse(any((path.endswith('/mesa') for path, _ in fake.calls[n:])))
            store.db.close()

    def test_exhausted_transient_failures_finish_after_three_attempts(self):

        class Broken(FakeSession):

            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                if urlsplit(url).path.endswith('/resumen/mesa'):
                    r.status_code = 500
                    r._content = b'{"error":"down"}'
                return r
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=3, rps=100000, reserve_gib=1)
            fake = Broken()
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0):
                store.run()
            self.assertTrue((Path(td) / 'finished.json').exists())
            self.assertEqual(store.totals()['retry_pending'], 0)
            rows = store.db.execute("SELECT attempts,ok FROM responses WHERE path='/v1/resumen/mesa'").fetchall()
            self.assertEqual(len(rows), 16)
            self.assertTrue(all((r['attempts'] == 3 and r['ok'] == 0 for r in rows)))
            m = json.loads((Path(td) / 't5/202605/manifest.json').read_text())
            self.assertTrue(m['catalog_coverage_complete'])
            self.assertFalse(m['mesa_data_complete'])
            self.assertFalse(m['data_complete'])
            store.db.close()

    def test_recovered_response_invalidates_export_even_if_interrupted_before_retry_checkpoint(self):

        class BrokenOnce(FakeSession):
            broken = True

            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                p = dict(parse_qsl(urlsplit(url).query))
                if self.broken and urlsplit(url).path.endswith('/resumen/mesa') and (p['provincia'] == '4') and (p['tconvocatoria'] == '5'):
                    r.status_code = 500
                    r._content = b'{"error":"down"}'
                return r
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=2, rps=100000, reserve_gib=1)
            fake = BrokenOnce()
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0), patch.object(store, 'retry_pending'):
                store.run()
            row = store.db.execute('SELECT path,params,hash FROM responses WHERE ok=0').fetchone()
            old_hash = row['hash']
            fake.broken = False
            self.assertTrue(store.phase_done(5, 202605, 'final_export'))
            with patch.object(store, 'session', return_value=fake):
                store.fetch(row['path'], json.loads(row['params']), retry=True)
            self.assertFalse(store.phase_done(5, 202605, 'final_export'))
            store.db.close()
            store = a.Archive(td, workers=2, rps=100000, reserve_gib=1)
            with patch.object(store, 'session', return_value=fake):
                store.run()
            m = json.loads((Path(td) / 't5/202605/manifest.json').read_text())
            self.assertTrue(m['mesa_data_complete'])
            self.assertIsNotNone(store.db.execute('SELECT 1 FROM payloads WHERE hash=?', (old_hash,)).fetchone())
            store.db.close()

    def test_global_pause_rechecks_callers_already_waiting(self):
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, reserve_gib=1)
            clock = [0.0]
            delays = []
            store.next_request = 10

            def wait(delay):
                if not delays:
                    store.pause_rate(20)
                delays.append(delay)
                clock[0] += delay
            with patch.object(a.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(store, 'wait', side_effect=wait):
                store.wait_rate()
            self.assertEqual(delays, [10, 10])
            self.assertEqual(clock[0], 20)
            store.db.close()
class StartupConcurrencyTests(unittest.TestCase):
    def test_slow_andalucia_aggregate_does_not_block_provincial_work(self):
        import threading
        provincial_started = threading.Event()

        class SlowRoot(FakeSession):
            def get(self, url, timeout=None):
                path = urlsplit(url).path
                if path.endswith('/resumen/provincia'):
                    provincial_started.set()
                if path.endswith('/resumen/cautonoma'):
                    if not provincial_started.wait(1):
                        raise AssertionError('Las provincias esperan al agregado de Andalucía')
                return super().get(url, timeout)

        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=4, rps=100000, reserve_gib=1)
            store.paths = {path: methods['get'] for path, methods in DOC['paths'].items() if 'get' in methods}
            provinces = [{'clave': p, 'valor': str(p)} for p in (4, 11, 14, 18, 21, 23, 29, 41)]
            with patch.object(store, 'session', return_value=SlowRoot()):
                store.download_core(5, 202605, provinces)
            self.assertTrue(provincial_started.is_set())
            self.assertEqual(store.totals()['mesas_completed'], 8)
            store.db.close()

if __name__ == '__main__':
    unittest.main()
