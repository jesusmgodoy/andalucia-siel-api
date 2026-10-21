import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_archive import a, FakeSession, DOC
from test_downloader import record, dm
from andalucia_siel.archive_audit import reconcile_coverage, failure_report
from andalucia_siel.quality import assess_record


class ArchiveRepairTests(unittest.TestCase):
    def store(self, directory):
        return a.Archive(directory, workers=2, rps=100000, reserve_gib=1, max_attempts=1)

    def seed(self, store):
        fake = FakeSession()
        with patch.object(store, 'session', return_value=fake):
            store.run()
        return fake

    def test_old_synthetic_zero_is_incomplete_and_never_exports_known_candidate_zeros(self):
        item = record()
        for key in ('votostotales', 'votosvalidos', 'votosnulos', 'votosblanco', 'votoscandidatura'):
            item['resumen'][key] = 0
        item['resumen']['abstenciones'] = item['resumen']['censo']
        item['escrutinio']['votos'] = []
        item['estado_descarga'] = 'ok_sin_votos'
        item['errors'] = [{'endpoint': '/v1/escrutinio/ambito/mesa', 'status_code': 500}]
        before = copy.deepcopy(item)
        self.assertEqual(assess_record(item)['estado_calidad'], 'incompleto')
        self.assertFalse(dm.party_votes_are_known(item))
        self.assertEqual(item, before)
        item['errors'] = []
        self.assertEqual(assess_record(item)['estado_calidad'], 'ok')

    def test_current_zero_summary_does_not_fabricate_a_successful_scrutiny(self):
        class BrokenScrutiny(FakeSession):
            def get(self, url, timeout=None):
                r = super().get(url, timeout)
                if '/resumen/mesa' in url:
                    body = r.json()
                    for field in ('votostotales', 'votosvalidos', 'votosnulos', 'votosblanco', 'votoscandidatura'):
                        body[field] = 0
                    body['abstenciones'] = body['censo']
                    r._content = json.dumps(body).encode()
                elif '/ambito/mesa' in url:
                    r.status_code = 500
                return r
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            fake = BrokenScrutiny()
            store.paths = {p: m['get'] for p, m in DOC['paths'].items() if 'get' in m}
            params = {'cautonoma': 1, 'tconvocatoria': 5, 'fconvocatoria': 202605,
                      'provincia': 4, 'municipio': 1, 'distrito': 1, 'seccion': '0001', 'mesa': 'A'}
            with patch.object(store, 'session', return_value=fake):
                store.pair('mesa', params)
            rec = store.record_pair('mesa', params, {})
            self.assertEqual(rec['estado_descarga'], 'resumen_cero_sin_escrutinio')
            self.assertEqual(rec['escrutinio'], {})
            self.assertFalse(dm.party_votes_are_known(rec))
            self.assertEqual(rec['resumen']['votostotales'], 0)
            store.db.close()

    def test_physical_reference_resolves_aggregate_count_only_if_every_province_matches(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.seed(store)
            reference = {'5/202605': {'total': 8, 'provinces': {str(n): 1 for n in (4, 11, 14, 18, 21, 23, 29, 41)}, 'source': 'official-fixture'}}
            original = store.result
            def changed(row, *args, **kwargs):
                data = original(row, *args, **kwargs)
                if row and row['path'] == '/v1/resumen/cautonoma':
                    data = {**data, 'nummesas': 16}
                return data
            audit = reconcile_coverage(store.db, changed, 5, 202605, reference)
            self.assertTrue(audit['catalog_coverage_complete'])
            self.assertEqual(audit['basis'], 'official_physical_tables')
            self.assertFalse(reconcile_coverage(store.db, changed, 5, 202605, {})['catalog_coverage_complete'])
            bad = copy.deepcopy(reference)
            bad['5/202605']['provinces']['4'] = 2
            bad['5/202605']['provinces']['11'] = 0
            self.assertFalse(reconcile_coverage(store.db, store.result, 5, 202605, bad)['catalog_coverage_complete'])
            store.db.close()

    def test_extra_catalog_entry_is_reported_not_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.seed(store)
            row = store.db.execute("SELECT params,context FROM nodes WHERE t=5 AND f=202605 AND level='mesa' LIMIT 1").fetchone()
            params, context = json.loads(row['params']), json.loads(row['context'])
            params['mesa'] = 'EXTRA'
            context['mesa_valor'] = 'EXTRA'
            store.node('mesa', params, context)
            audit = reconcile_coverage(store.db, store.result, 5, 202605, {})
            self.assertEqual(audit['catalog_count'], 9)
            self.assertTrue(audit['municipal_mismatches'])
            self.assertFalse(audit['catalog_coverage_complete'])
            self.assertEqual(store.db.execute("SELECT count(*) FROM nodes WHERE t=5 AND level='mesa'").fetchone()[0], 9)
            store.db.close()

    def test_repair_is_offline_and_preserves_all_original_bytes_and_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            self.seed(store)
            before = [tuple(r) for r in store.db.execute('SELECT key,hash,ok,attempts FROM responses ORDER BY key')]
            payloads = [tuple(r) for r in store.db.execute('SELECT * FROM payloads ORDER BY hash')]
            attempts = store.db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            finished_at = json.loads((Path(td) / 'finished.json').read_text())['finished_at']
            with patch.object(store, 'session', side_effect=AssertionError('No network during offline repair')):
                store.repair()
            self.assertEqual(before, [tuple(r) for r in store.db.execute('SELECT key,hash,ok,attempts FROM responses ORDER BY key')])
            self.assertEqual(payloads, [tuple(r) for r in store.db.execute('SELECT * FROM payloads ORDER BY hash')])
            self.assertEqual(attempts, store.db.execute('SELECT count(*) FROM attempts').fetchone()[0])
            self.assertEqual(json.loads((Path(td) / 'finished.json').read_text())['finished_at'], finished_at)
            self.assertTrue(json.loads((Path(td) / 'repair.json').read_text())['offline'])
            self.assertTrue((Path(td) / 't5/202605/incidencias_origen.json').exists())
            store.db.close()

    def test_targeted_recovery_has_one_extra_attempt_and_keeps_failed_budget_exhausted(self):
        class Broken(FakeSession):
            def get(self, url, timeout=None):
                response = super().get(url, timeout)
                if '/celectos' in url:
                    response.status_code = 500
                return response
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            fake = Broken()
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0):
                store.run()
            before = len(fake.calls)
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0):
                store.repair(['/v1/celectos'], retry_limit=1)
            self.assertEqual(len(fake.calls) - before, 1)
            self.assertEqual(json.loads((Path(td) / 'repair.json').read_text())['retried'], 1)
            self.assertEqual(store.totals()['retry_pending'], 0)
            self.assertEqual(sorted(r[0] for r in store.db.execute("SELECT attempts FROM responses WHERE path='/v1/celectos'")), [1, 2])
            store.db.close()

    def test_missing_metadata_does_not_trigger_implicit_network(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            with patch.object(store, 'session') as session:
                with self.assertRaises(ValueError):
                    store.repair()
                session.assert_not_called()
            store.db.close()



class RecoverySuccessTests(unittest.TestCase):
    def test_successful_targeted_recovery_keeps_previous_payload_and_history(self):
        class Toggle(FakeSession):
            broken = True
            def get(self, url, timeout=None):
                response = super().get(url, timeout)
                if self.broken and '/celectos' in url:
                    response.status_code = 500
                return response
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=2, rps=100000, reserve_gib=1, max_attempts=1)
            fake = Toggle()
            with patch.object(store, 'session', return_value=fake), patch.object(store, 'retry_delay', return_value=0):
                store.run()
            old_hash = store.db.execute("SELECT hash FROM responses WHERE ok=0 AND path='/v1/celectos' LIMIT 1").fetchone()[0]
            old_attempts = store.db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            fake.broken = False
            with patch.object(store, 'session', return_value=fake):
                store.repair(['/v1/celectos'], 1)
            self.assertEqual(json.loads((Path(td) / 'repair.json').read_text())['recovered'], 1)
            self.assertIsNotNone(store.db.execute('SELECT hash FROM payloads WHERE hash=?', (old_hash,)).fetchone())
            self.assertEqual(store.db.execute('SELECT count(*) FROM attempts').fetchone()[0], old_attempts + 1)
            store.db.close()

class IssueClassificationTests(unittest.TestCase):
    def test_empty_selector_classification_never_erases_or_hides_failed_responses(self):
        class NoDetail(FakeSession):
            def get(self, url, timeout=None):
                response = super().get(url, timeout)
                if '/opciones/distrito' in url:
                    response._content = b'[]'
                if '/resumen/municipio' in url or '/ambito/municipio' in url:
                    response.status_code = 500
                return response
        with tempfile.TemporaryDirectory() as td:
            store = a.Archive(td, workers=2, rps=100000, reserve_gib=1, max_attempts=1)
            store.paths = {p: m['get'] for p, m in DOC['paths'].items() if 'get' in m}
            params = {'cautonoma': 1, 'tconvocatoria': 5, 'fconvocatoria': 202605, 'provincia': 4, 'municipio': 1}
            with patch.object(store, 'session', return_value=NoDetail()):
                store.options('distrito', params)
                store.pair('municipio', params)
            before = [tuple(r) for r in store.db.execute('SELECT * FROM responses ORDER BY key')]
            report = failure_report(store.db, store.result, store.identity)
            self.assertEqual(report['failed_queries'], 2)
            self.assertEqual(report['by_category'], {'municipio_sin_desglose_en_api': 2})
            self.assertTrue(all(r['status'] == 500 for r in report['details']))
            self.assertEqual(before, [tuple(r) for r in store.db.execute('SELECT * FROM responses ORDER BY key')])
            store.db.close()

if __name__ == '__main__':
    unittest.main()
