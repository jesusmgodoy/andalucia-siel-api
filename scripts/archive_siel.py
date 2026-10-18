#!/usr/bin/env python3
"""Archivo reanudable de los GET de SIEL para Parlamento de Andalucía y referendos.

Las conversiones POST JSON->XML no añaden datos de origen y no se solicitan.
SQLite conserva cada respuesta exacta comprimida, su URL, fecha y hash. Primero
se descargan y exportan mesas/CERA/agregados de todas las convocatorias; después
las vistas por candidatura y los reintentos. No incluye otras elecciones.
"""
from __future__ import annotations
import argparse
import base64
import concurrent.futures
import csv
from collections import deque
import fcntl
import gzip
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import requests

BASE = 'https://ws040.juntadeandalucia.es/siel-api'
SELECTED_TYPES = (5, 1)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
PERMANENT_HTTP = tuple(code for code in range(400, 500) if code not in (408, 425, 429))
FIELDS = ['censo', 'abstenciones', 'votostotales', 'votosnulos', 'votosvalidos', 'votosblanco', 'votoscandidatura', 'nummesas']


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


class SourceUnavailable(Exception):
    pass


class DiskReserveError(RuntimeError):
    pass


class StopRequested(Exception):
    pass


class Archive:
    def __init__(self, out, workers=6, rps=6, reserve_gib=20, max_attempts=3, timeout=45):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.out / 'archivo.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=NORMAL;
          CREATE TABLE IF NOT EXISTS payloads(hash TEXT PRIMARY KEY, body BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS responses(
            key TEXT PRIMARY KEY, path TEXT NOT NULL, params TEXT NOT NULL,
            t INTEGER, f INTEGER, status INTEGER, ok INTEGER NOT NULL,
            attempts INTEGER NOT NULL, fetched_at TEXT, url TEXT, hash TEXT, error TEXT, headers TEXT);
          CREATE INDEX IF NOT EXISTS response_election ON responses(t,f,path);
          CREATE INDEX IF NOT EXISTS response_availability ON responses(ok);
          CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY, key TEXT, fetched_at TEXT, status INTEGER, hash TEXT, error TEXT);
          CREATE TABLE IF NOT EXISTS nodes(
            key TEXT PRIMARY KEY,t INTEGER,f INTEGER,level TEXT,params TEXT,context TEXT);
          CREATE INDEX IF NOT EXISTS node_election ON nodes(t,f,level);
          CREATE TABLE IF NOT EXISTS jobs(t INTEGER,f INTEGER,state TEXT,details TEXT,updated_at TEXT,
            PRIMARY KEY(t,f));
          CREATE TABLE IF NOT EXISTS branches(
            key TEXT PRIMARY KEY,t INTEGER,f INTEGER,params TEXT,error TEXT,updated_at TEXT);
        ''')
        # Additive migration: databases produced by the standalone VPS runner
        # retain all payloads, response identities and attempt history.
        for table, column, declaration in (
            ('responses', 'next_retry_at', 'REAL NOT NULL DEFAULT 0'),
            ('attempts', 'duration_ms', 'INTEGER'),
        ):
            columns = {row[1] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if column not in columns:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS archive_meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS phases(t INTEGER,f INTEGER,phase TEXT,updated_at TEXT,
                PRIMARY KEY(t,f,phase));
            CREATE TABLE IF NOT EXISTS node_requests(
                node_key TEXT PRIMARY KEY,resumen_key TEXT,escrutinio_key TEXT);
            CREATE INDEX IF NOT EXISTS response_retry ON responses(ok,next_retry_at);
        ''')
        self.lock = threading.RLock()
        self.rate_lock = threading.Lock()
        self.request_slots = threading.BoundedSemaphore(workers)
        self.thread = threading.local()
        self.interval = 1 / rps
        self.next_request = 0.0
        self.reserve = int(reserve_gib * 1024**3)
        self.max_attempts = max_attempts
        self.workers = workers
        self.timeout = timeout
        self.stop = threading.Event()
        self.query_locks = [threading.Lock() for _ in range(256)]
        self.metrics_lock = threading.Lock()
        self.latencies = deque(maxlen=500)
        self.in_flight = {}
        self.max_pending_observed = 0
        self.last_progress = 0.0
        self.new_responses = 0
        self.paths = {}
        self.current = {'state': 'starting'}
        self.started = now()

    def disk_check(self):
        if shutil.disk_usage(self.out).free < self.reserve:
            raise DiskReserveError('Se ha alcanzado la reserva de espacio libre; descarga detenida.')

    def session(self):
        if not hasattr(self.thread, 'session'):
            s = requests.Session()
            s.headers.update({'Accept': 'application/json', 'User-Agent': 'andalucia-siel-archive/2.0'})
            s.verify = True
            self.thread.session = s
        return self.thread.session

    def check_stop(self):
        if self.stop.is_set():
            raise StopRequested('Parada solicitada; se conserva el punto de reanudación.')

    def wait(self, delay):
        if self.stop.wait(max(0, delay)):
            self.check_stop()

    def wait_rate(self):
        # Recheck after every wait: Retry-After also applies to callers that
        # were already waiting when another worker received 429/503.
        while True:
            self.check_stop()
            with self.rate_lock:
                current = time.monotonic()
                delay = self.next_request - current
                if delay <= 0:
                    self.next_request = current + self.interval
                    return
            self.wait(delay)

    def pause_rate(self, delay):
        with self.rate_lock:
            self.next_request = max(self.next_request, time.monotonic() + delay)

    @staticmethod
    def retry_after(response):
        value = response.headers.get('Retry-After') if response is not None else None
        if value:
            try:
                seconds = float(value)
                return max(0, seconds) if math.isfinite(seconds) else 0
            except ValueError:
                try:
                    return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        return 0

    def retry_delay(self, attempt, response):
        return max(min(30, 2 ** attempt), self.retry_after(response))

    def params_for(self, path, params):
        if path in self.paths:
            names = [p['name'] for p in self.paths[path].get('parameters', []) if p.get('in') == 'query']
            missing = [p['name'] for p in self.paths[path].get('parameters', [])
                       if p.get('required') and p.get('in') == 'query' and p['name'] not in params]
            if missing:
                raise ValueError(f'{path}: parámetros ausentes {missing}')
            return {k: params[k] for k in names if k in params}
        return dict(params)

    def identity(self, path, params):
        p = self.params_for(path, params)
        return hashlib.sha256((path + '?' + canonical(p)).encode()).hexdigest(), p

    def row(self, path, params):
        key, _ = self.identity(path, params)
        with self.lock:
            return self.db.execute('SELECT * FROM responses WHERE key=?', (key,)).fetchone()

    def body(self, row):
        if not row or not row['hash']:
            return b''
        with self.lock:
            payload = self.db.execute('SELECT body FROM payloads WHERE hash=?', (row['hash'],)).fetchone()
        return zlib.decompress(payload[0])

    def result(self, row, catalog=False):
        if not row or not row['ok']:
            if catalog:
                raise SourceUnavailable(f'{row["url"] if row else "consulta ausente"}: {row["error"] if row else "sin respuesta"}')
            return None
        data = json.loads(self.body(row))
        if catalog and (not isinstance(data, list) or any(not isinstance(x, dict) or 'clave' not in x or 'valor' not in x for x in data)):
            raise SourceUnavailable(f'{row["url"]}: catálogo con estructura inesperada')
        return data

    def fetch(self, path, params=None, catalog=False, retry=False, refresh=False):
        params = params or {}
        if path.startswith('/v1/') and self.paths and path not in self.paths:
            return [] if catalog else None
        key, p = self.identity(path, params)
        # Coalesce simultaneous requests for the same identity without an
        # unbounded lock dictionary. Successful cached responses never hit HTTP.
        with self.query_locks[int(key[:8], 16) % len(self.query_locks)]:
            row = self.row(path, p)
            if row and not refresh and (row['ok'] or (row['attempts'] > 0 and (not retry
                        or row['attempts'] >= self.max_attempts or row['status'] in PERMANENT_HTTP))):
                return self.result(row, catalog)
            self.check_stop()
            self.disk_check()
            if row and not refresh and row['next_retry_at']:
                self.wait(row['next_retry_at'] - time.time())
            attempt = (row['attempts'] if row and not refresh else 0) + 1
            url = BASE + path + ('?' + urlencode(p) if p else '')
            status, content, headers, error, ok = None, b'', {}, None, False
            response = None
            started = time.monotonic()
            with self.request_slots:
                self.wait_rate()
                started = time.monotonic()
                with self.metrics_lock:
                    self.in_flight[key] = (path, started)
                try:
                    response = self.session().get(url, timeout=(10, self.timeout))
                    status, content = response.status_code, response.content
                    headers = {k: response.headers[k] for k in ('Content-Type', 'Date', 'ETag', 'Last-Modified', 'Retry-After') if k in response.headers}
                    if status == 200:
                        try:
                            data = json.loads(content)
                            if catalog and (not isinstance(data, list) or any(not isinstance(x, dict) or 'clave' not in x or 'valor' not in x for x in data)):
                                raise ValueError('Catálogo con estructura inesperada')
                            ok = True
                        except (ValueError, UnicodeDecodeError):
                            error = 'Respuesta 200 sin JSON válido o catálogo con estructura inesperada'
                    else:
                        error = f'HTTP {status}'
                except requests.RequestException as exc:
                    error = f'{type(exc).__name__}: {exc}'
                finally:
                    duration_ms = round((time.monotonic() - started) * 1000)
                    with self.metrics_lock:
                        self.in_flight.pop(key, None)
                        self.latencies.append((path, duration_ms, status, ok))
            delay = self.retry_delay(attempt, response)
            if status in (429, 503):
                self.pause_rate(delay)
            digest = hashlib.sha256(content).hexdigest()
            # Compression is CPU work and must not serialize SQLite readers.
            compressed = zlib.compress(content, 6)
            timestamp = now()
            with self.lock:
                self.db.execute('INSERT OR IGNORE INTO payloads VALUES(?,?)', (digest, compressed))
                self.db.execute('INSERT INTO attempts(key,fetched_at,status,hash,error,duration_ms) VALUES(?,?,?,?,?,?)',
                                (key, timestamp, status, digest, error, duration_ms))
                self.db.execute('''INSERT INTO responses(key,path,params,t,f,status,ok,attempts,fetched_at,url,hash,error,headers,next_retry_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET status=excluded.status,ok=excluded.ok,attempts=excluded.attempts,
                    fetched_at=excluded.fetched_at,hash=excluded.hash,error=excluded.error,headers=excluded.headers,
                    next_retry_at=excluded.next_retry_at''',
                    (key, path, canonical(p), p.get('tconvocatoria'), p.get('fconvocatoria'), status, int(ok), attempt,
                     timestamp, url, digest, error, canonical(headers), 0 if ok else time.time() + delay))
                # Invalidate exports in the same transaction as the response.
                # A stop during retries must never leave a stale 'finished' file.
                if p.get('tconvocatoria') is not None and p.get('fconvocatoria') is not None:
                    self.db.execute("DELETE FROM phases WHERE t=? AND f=? AND phase='final_export'",
                                    (p['tconvocatoria'], p['fconvocatoria']))
                if ok and row and not row['ok'] and '/opciones/' in path:
                    clauses, args = [], []
                    for field, column in (('tconvocatoria', 't'), ('fconvocatoria', 'f')):
                        if p.get(field) is not None:
                            clauses.append(column + '=?'); args.append(p[field])
                    self.db.execute('DELETE FROM phases' + (' WHERE ' + ' AND '.join(clauses) if clauses else ''), args)
                self.db.commit()
                self.new_responses += 1
            return self.result(self.row(path, p), catalog)

    def critical(self, path, params=None, catalog=False, refresh=False):
        # Startup metadata is required to construct a trustworthy plan. Only
        # these few queries retry immediately; result retries are a final phase.
        for attempt in range(self.max_attempts):
            try:
                value = self.fetch(path, params, catalog=catalog, retry=True, refresh=refresh and attempt == 0)
                if value is not None:
                    return value
            except SourceUnavailable:
                pass
            row = self.row(path, params or {})
            if row and (row['attempts'] >= self.max_attempts or row['status'] in PERMANENT_HTTP):
                break
        raise SourceUnavailable(f'No se ha podido obtener el catálogo inicial: {path}')

    def options(self, name, params=None):
        return self.fetch('/v1/opciones/' + name, params, catalog=True)

    def node(self, level, params, context):
        key = hashlib.sha256((level + canonical(params)).encode()).hexdigest()
        with self.lock:
            self.db.execute('''INSERT INTO nodes(key,t,f,level,params,context) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(key) DO UPDATE SET context=excluded.context
                            WHERE nodes.context<>excluded.context''',
                            (key, params['tconvocatoria'], params['fconvocatoria'], level, canonical(params), canonical(context)))
            if level == 'mesa':
                self.db.execute('INSERT OR IGNORE INTO node_requests VALUES(?,?,?)',
                                (key, self.identity('/v1/resumen/mesa', params)[0],
                                 self.identity('/v1/escrutinio/ambito/mesa', params)[0]))
            self.db.commit()
        return key

    def branch_error(self, params, error):
        key = hashlib.sha256(canonical(params).encode()).hexdigest()
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO branches VALUES(?,?,?,?,?,?)',
                            (key, params['tconvocatoria'], params['fconvocatoria'], canonical(params), str(error), now()))
            self.db.commit()
        logging.warning('Catálogo no disponible %s: %s', canonical(params), error)

    def clear_branch(self, params):
        key = hashlib.sha256(canonical(params).encode()).hexdigest()
        with self.lock:
            self.db.execute('DELETE FROM branches WHERE key=?', (key,))
            self.db.commit()

    def totals(self, t=None, f=None):
        where, params = (' WHERE t=? AND f=?', (t, f)) if t is not None else ('', ())
        with self.lock:
            counts = self.db.execute('SELECT COUNT(*) AS total,COALESCE(SUM(ok),0) AS ok FROM responses' + where, params).fetchone()
            levels = self.db.execute('SELECT level,COUNT(*) n FROM nodes' + where + ' GROUP BY level', params).fetchall()
            failures = self.db.execute('SELECT COUNT(*) FROM branches' + where, params).fetchone()[0]
            completed = self.db.execute('''SELECT COUNT(*) FROM node_requests nr
                JOIN nodes n ON n.key=nr.node_key
                JOIN responses a ON a.key=nr.resumen_key AND a.ok=1
                JOIN responses b ON b.key=nr.escrutinio_key AND b.ok=1'''
                + (' WHERE n.t=? AND n.f=?' if t is not None else ''), params).fetchone()[0]
            retryable = self.db.execute('''SELECT COUNT(*) FROM responses WHERE ok=0 AND attempts<?
                AND (attempts=0 OR status IS NULL OR status>=500 OR status IN(200,408,425,429))'''
                + (' AND t=? AND f=?' if t is not None else ''), (self.max_attempts, *params)).fetchone()[0]
        return {'queries': counts['total'], 'ok': counts['ok'], 'source_unavailable': counts['total'] - counts['ok'],
                'nodes': {r['level']: r['n'] for r in levels}, 'mesas_completed': completed,
                'retry_pending': retryable, 'unavailable_catalog_branches': failures}

    def progress(self):
        with self.lock:
            with self.metrics_lock:
                samples = list(self.latencies)
                active = [{'endpoint': p, 'seconds': round(time.monotonic() - started, 1)}
                          for p, started in self.in_flight.values()]
            endpoints = {}
            for path, ms, status, ok in samples:
                entry = endpoints.setdefault(path, {'samples': 0, 'total_ms': 0, 'failed': 0})
                entry['samples'] += 1; entry['total_ms'] += ms; entry['failed'] += not ok
            for entry in endpoints.values():
                entry['mean_seconds'] = round(entry.pop('total_ms') / entry['samples'] / 1000, 3)
            phases = [dict(row) for row in self.db.execute('SELECT * FROM phases ORDER BY t,f,phase')]
            data = {'started_at': self.started, 'updated_at': now(), 'pid': os.getpid(), **self.current,
                    'totals': self.totals(), 'disk_free_bytes': shutil.disk_usage(self.out).free,
                    'tls_verified': True, 'selected_types': list(SELECTED_TYPES), 'phases': phases,
                    'in_flight': active, 'recent_endpoints': endpoints,
                    'workers': self.workers, 'max_rps': 1 / self.interval,
                    'max_pending_futures': self.max_pending_observed}
            if self.current.get('tconvocatoria') is not None:
                data['election_totals'] = self.totals(self.current['tconvocatoria'], self.current['fconvocatoria'])
            atomic_json(self.out / 'progress.json', data)
            self.last_progress = time.monotonic()
            logging.info('Progreso %s', canonical({'current': self.current, **data['totals']}))

    def pair(self, level, params, cera=False):
        extra = 'rausentes/' if cera else ''
        for prefix in ('/v1/resumen/', '/v1/escrutinio/ambito/'):
            self.fetch(prefix + extra + level, params)

    def drain(self, items, worker):
        """Expand a territorial graph with bounded futures, never a worker per town.

        Workers return children to the coordinator instead of waiting for child
        futures. A single large municipality can therefore use the whole pool.
        """
        ready = deque(items)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            pending = set()
            while ready or pending:
                self.check_stop()
                while ready and len(pending) < self.workers * 2:
                    pending.add(pool.submit(worker, ready.popleft()))
                    self.max_pending_observed = max(self.max_pending_observed, len(pending))
                done, pending = concurrent.futures.wait(pending, timeout=1,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    children = future.result()
                    if children:
                        ready.extend(children)
                if time.monotonic() - self.last_progress >= 30:
                    self.progress()

    def phase_done(self, t, f, phase):
        with self.lock:
            return self.db.execute('SELECT 1 FROM phases WHERE t=? AND f=? AND phase=?', (t, f, phase)).fetchone() is not None

    def mark_phase(self, t, f, phase):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO phases VALUES(?,?,?,?)', (t, f, phase, now()))
            self.db.commit()

    def core_node(self, item):
        level, params, context = item
        self.check_stop()
        self.node(level, params, context)
        self.pair(level, params)
        if level in ('cautonoma', 'provincia'):
            self.pair(level, params, cera=True)
        child_level = {'provincia': 'municipio', 'municipio': 'distrito', 'distrito': 'seccion', 'seccion': 'mesa'}.get(level)
        if child_level is None:
            return []
        try:
            children = self.options(child_level, params)
        except SourceUnavailable as exc:
            self.branch_error(params, exc)
            return []
        self.clear_branch(params)
        result = []
        for child in children:
            value = child['valor'] if child_level in ('seccion', 'mesa') else int(child['clave'])
            child_params = {**params, child_level: value}
            label = 'valor' if child_level in ('seccion', 'mesa') else 'nombre'
            child_context = {**context, child_level + '_clave': child['clave'], child_level + '_' + label: child['valor']}
            result.append((child_level, child_params, child_context))
        return result

    def download_core(self, t, f, provinces):
        if self.phase_done(t, f, 'core'):
            return
        self.current = {'state': 'downloading', 'phase': 'core', 'tconvocatoria': t, 'fconvocatoria': f}
        self.progress()
        base = {'cautonoma': 1, 'tconvocatoria': t, 'fconvocatoria': f}
        # Root aggregates share the pool with provinces. A slow Andalucía/CERA
        # response must not keep every other worker idle at election startup.
        items = [('cautonoma', base, {'tconvocatoria': t, 'fconvocatoria': f})]
        items += [('provincia', {**base, 'provincia': int(p['clave'])},
                  {'tconvocatoria': t, 'fconvocatoria': f, 'provincia_clave': int(p['clave']), 'provincia_nombre': p['valor']})
                 for p in provinces]
        self.drain(items, self.core_node)
        self.mark_phase(t, f, 'core')

    def distribution_node(self, item):
        level, params = item
        if level == 'request':
            self.fetch(*params)
            return []
        try:
            parties = self.options('partido/' + level, params)
        except SourceUnavailable as exc:
            logging.warning('Catálogo de candidaturas no disponible: %s', exc)
            return []
        return [('request', ('/v1/escrutinio/partido/' + level, {**params, 'partido': p['clave']})) for p in parties]

    def download_distributions(self, t, f):
        if self.phase_done(t, f, 'distributions'):
            return
        self.current = {'state': 'downloading', 'phase': 'distributions', 'tconvocatoria': t, 'fconvocatoria': f}
        self.progress()
        base = {'cautonoma': 1, 'tconvocatoria': t, 'fconvocatoria': f}
        self.fetch('/v1/celectos', base)
        with self.lock:
            rows = self.db.execute("SELECT level,params FROM nodes WHERE t=? AND f=? AND level IN ('cautonoma','provincia','municipio')", (t, f)).fetchall()
        self.drain([(row['level'], json.loads(row['params'])) for row in rows], self.distribution_node)
        self.mark_phase(t, f, 'distributions')

    def retry_one(self, row):
        self.fetch(row['path'], json.loads(row['params']), catalog='/opciones/' in row['path'], retry=True)
        return []

    def retry_pending(self, elections, provinces):
        # One attempt per task. Backoff stays in SQLite between passes and does
        # not occupy workers while other queries are ready.
        while True:
            self.check_stop()
            with self.lock:
                rows = self.db.execute('''SELECT * FROM responses WHERE ok=0 AND attempts<?
                    AND (attempts=0 OR status IS NULL OR status>=500 OR status IN(200,408,425,429))
                    ORDER BY next_retry_at,key''', (self.max_attempts,)).fetchall()
            if not rows:
                return
            ready = [r for r in rows if r['next_retry_at'] <= time.time()]
            if not ready:
                self.wait(rows[0]['next_retry_at'] - time.time())
                continue
            self.current = {'state': 'downloading', 'phase': 'retries'}
            self.progress()
            # Invalid catalogs remain explicit branch failures; retry all
            # candidates even if one catalog is still unavailable.
            def work(row):
                try:
                    return self.retry_one(row)
                except SourceUnavailable:
                    return []
            self.drain(ready, work)
            changed = {(t, f) for t, f in elections for r in ready
                       if (r['t'] is None or r['t'] == t) and (r['f'] is None or r['f'] == f)}
            with self.lock:
                self.db.executemany("DELETE FROM phases WHERE t=? AND f=? AND phase='final_export'", sorted(changed))
                self.db.commit()
            recovered_catalogs = [r for r in ready if '/opciones/' in r['path'] and self.row(r['path'], json.loads(r['params']))['ok']]
            if recovered_catalogs:
                affected = {(t, f) for t, f in elections for r in recovered_catalogs
                            if (r['t'] is None or r['t'] == t) and (r['f'] is None or r['f'] == f)}
                with self.lock:
                    self.db.executemany('DELETE FROM phases WHERE t=? AND f=?', sorted(affected))
                    self.db.commit()
                for t, f in sorted(affected):
                    self.download_core(t, f, provinces)
                    self.export_election(t, f, provinces, stage='core')
                for t, f in sorted(affected):
                    self.download_distributions(t, f)

    def backfill_node_requests(self):
        with self.lock:
            nodes = self.db.execute('''SELECT n.key,n.params FROM nodes n LEFT JOIN node_requests r
                ON n.key=r.node_key WHERE n.level='mesa' AND r.node_key IS NULL''').fetchall()
            self.db.executemany('INSERT OR IGNORE INTO node_requests VALUES(?,?,?)',
                [(r['key'], self.identity('/v1/resumen/mesa', json.loads(r['params']))[0],
                  self.identity('/v1/escrutinio/ambito/mesa', json.loads(r['params']))[0]) for r in nodes])
            self.db.commit()

    def record_pair(self, level, params, context, cera=False):
        extra = 'rausentes/' if cera else ''
        paths = {'resumen': '/v1/resumen/' + extra + level,
                 'escrutinio': '/v1/escrutinio/ambito/' + extra + level}
        result = {'context': context, 'source': {'api_base': BASE, 'params': params}, 'errors': [],
                  'fuente_registro': 'api_cera' if cera else 'api_mesa', 'estado_descarga': 'ok'}
        for field, path in paths.items():
            row = self.row(path, params)
            result['source'][field + '_url'] = row['url'] if row else BASE + path + '?' + urlencode(params)
            if row and row['ok']:
                value = self.result(row)
                result[field] = value if isinstance(value, dict) else {}
            else:
                result[field] = {}
                result['errors'].append({'endpoint': path, 'status_code': row['status'] if row else None,
                                         'message': row['error'] if row else 'No solicitado'})
        if result['errors']:
            result['estado_descarga'] = 'cera_no_disponible' if cera else 'mesa_no_disponible' if not result['resumen'] else 'escrutinio_no_disponible'
            if not cera and result['resumen'].get('votostotales') == 0 and result['resumen'].get('votoscandidatura') == 0:
                result['estado_descarga'] = 'ok_sin_votos'
                result['escrutinio'] = {'idescrutinio': result['resumen'].get('idescrutinio'), 'votos': []}
        return result

    def export_election(self, t, f, provinces, stage='final'):
        self.current = {'state': 'exporting', 'phase': stage, 'tconvocatoria': t, 'fconvocatoria': f}
        self.progress()
        self.disk_check()
        target = self.out / f't{t}' / str(f)
        target.mkdir(parents=True, exist_ok=True)
        # Build off to the side. A failed/interrupted export never truncates a
        # previously published file; publish the manifest after all data files.
        with tempfile.TemporaryDirectory(prefix='.export-', dir=target.parent) as temp:
            folder = Path(temp)
            manifest = self.write_exports(t, f, provinces, folder, stage)
            for source in sorted(folder.iterdir(), key=lambda p: p.name == 'manifest.json'):
                self.check_stop()
                source.replace(target / source.name)
            suffix = 'parcial' if manifest['catalog_coverage_complete'] else 'completo'
            (target / f'andalucia_t{t}_{f}_{suffix}.csv.gz').unlink(missing_ok=True)
        if stage == 'final':
            state = 'complete' if manifest['catalog_coverage_complete'] else 'source_limits'
            with self.lock:
                self.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)', (t, f, state, canonical(manifest), now()))
                self.db.commit()
        self.mark_phase(t, f, stage + '_export')
        logging.info('Convocatoria exportada t=%s f=%s fase=%s', t, f, stage)

    def write_exports(self, t, f, provinces, folder, stage):
        # SQLite is authoritative and holds exact response bytes. NDJSON is a
        # portable JSON representation with the matching body hash and URL.
        self.export_responses(folder / 'respuestas.ndjson.gz', 'WHERE t=? AND f=?', (t, f))
        self.export_responses(self.out / 'metadatos.ndjson.gz', 'WHERE f IS NULL', ())
        # Reuse the audited normalizer without its Parliament-only orchestrator.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import download_mesas as dm
        mesas_path = folder / 'mesas.ndjson.gz'
        with gzip.open(mesas_path, 'wt', encoding='utf-8') as handle, gzip.open(folder / 'mesas_catalogo.csv.gz', 'wt', encoding='utf-8', newline='') as catalog:
            writer = csv.DictWriter(catalog, fieldnames=dm.CONTEXT_FIELDS)
            writer.writeheader()
            cursor = self.db.execute("SELECT * FROM nodes WHERE t=? AND f=? AND level='mesa' ORDER BY params", (t, f))
            for node in cursor:
                self.check_stop()
                ctx = json.loads(node['context'])
                writer.writerow({k: ctx.get(k) for k in dm.CONTEXT_FIELDS})
                rec = self.record_pair('mesa', json.loads(node['params']), ctx)
                handle.write(canonical(rec) + '\n')
        cera_path = folder / 'cera.ndjson.gz'
        base = {'cautonoma': 1, 'tconvocatoria': t, 'fconvocatoria': f}
        with gzip.open(cera_path, 'wt', encoding='utf-8') as handle:
            for province in [None, *provinces]:
                params = {**base, **({'provincia': int(province['clave'])} if province else {})}
                scope = 'provincia' if province else 'cautonoma'
                ctx = {'tconvocatoria': t, 'fconvocatoria': f, 'ambito': scope,
                       'provincia_clave': int(province['clave']) if province else None,
                       'provincia_nombre': province['valor'] if province else None}
                handle.write(canonical(self.record_pair(scope, params, ctx, cera=True)) + '\n')
        stats = self.totals(t, f)
        summary = self.row('/v1/resumen/cautonoma', base)
        data = self.result(summary) if summary else None
        expected = data.get('nummesas') if isinstance(data, dict) else None
        mesa_count = stats['nodes'].get('mesa', 0)
        complete = stats['unavailable_catalog_branches'] == 0 and mesa_count > 0 and isinstance(expected, int) and mesa_count == expected
        combined = folder / f'andalucia_t{t}_{f}_{"completo" if complete else "parcial"}.csv'
        rows = dm.write_complete_csv(mesas_path, cera_path, combined)
        # Keep the user-facing CSVs compressed too.
        for source, target, writer in ((mesas_path, folder / 'mesas_largo.csv', dm.write_long_csv),
                                       (cera_path, folder / 'cera_largo.csv', dm.write_rausentes_long_csv)):
            writer(source, target)
            with target.open('rb') as src, gzip.open(str(target) + '.gz', 'wb') as dest:
                shutil.copyfileobj(src, dest)
            target.unlink()
        with combined.open('rb') as src, gzip.open(str(combined) + '.gz', 'wb') as dest:
            shutil.copyfileobj(src, dest)
        combined.unlink()
        self.export_tabular(t, f, folder)
        manifest = {'tconvocatoria': t, 'fconvocatoria': f, 'generated_at': now(), **stats,
                    'stage': stage, 'archive_finished': stage == 'final',
                    'mesa_data_complete': complete and stats['mesas_completed'] == mesa_count,
                    'data_complete': stage == 'final' and complete and stats['source_unavailable'] == 0
                                     and stats['mesas_completed'] == mesa_count,
                    'catalog_coverage_complete': complete, 'nummesas_api': expected, 'mesas_catalogadas': mesa_count,
                    'combined_rows': rows, 'files': sorted(p.name for p in folder.iterdir() if p.is_file()),
                    'data_note': 'Los errores de origen se conservan. Cobertura del catálogo no equivale a corrección del dato.',
                    'database': str(self.out / 'archivo.sqlite3')}
        atomic_json(folder / 'manifest.json', manifest)
        return manifest

    def export_responses(self, target, where, params):
        temp = target.with_name(target.name + '.tmp')
        with gzip.open(temp, 'wt', encoding='utf-8') as handle:
            cursor = self.db.execute('SELECT * FROM responses ' + where + ' ORDER BY path,params', params)
            for row in cursor:
                self.check_stop()
                data = {k: row[k] for k in row.keys() if k not in ('params', 'headers')}
                data['params'] = json.loads(row['params'])
                data['headers'] = json.loads(row['headers'])
                body = self.body(row)
                try:
                    data['response'] = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    data['response_bytes_base64'] = base64.b64encode(body).decode()
                handle.write(canonical(data) + '\n')
        temp.replace(target)

    def export_tabular(self, t, f, folder):
        from andalucia_siel.quality import assess_record
        keys = ['tconvocatoria', 'fconvocatoria', 'cautonoma', 'provincia', 'municipio', 'distrito', 'seccion', 'mesa', 'partido']
        common = ['request_id', 'endpoint', *keys, 'url', 'fetched_at', 'http_status', 'available']
        with gzip.open(folder / 'resumenes.csv.gz', 'wt', encoding='utf-8', newline='') as sh, \
             gzip.open(folder / 'escrutinios_largo.csv.gz', 'wt', encoding='utf-8', newline='') as vh:
            sw = csv.DictWriter(sh, fieldnames=common + FIELDS + ['estado_calidad', 'incidencias_calidad'])
            vw = csv.DictWriter(vh, fieldnames=common + ['conjunto', 'numvotos', 'porcentajeVotos', 'diputados'])
            sw.writeheader(); vw.writeheader()
            cursor = self.db.execute("SELECT * FROM responses WHERE t=? AND f=? AND (path LIKE '/v1/resumen/%' OR path LIKE '/v1/escrutinio/%') ORDER BY path,params", (t, f))
            for row in cursor:
                params = json.loads(row['params'])
                base = {'request_id': row['key'], 'endpoint': row['path'], **{k: params.get(k) for k in keys},
                        'url': row['url'], 'fetched_at': row['fetched_at'], 'http_status': row['status'], 'available': row['ok']}
                data = self.result(row) if row['ok'] else {}
                if not isinstance(data, dict):
                    data = {}
                if '/resumen/' in row['path']:
                    scrutiny_path = row['path'].replace('/v1/resumen/', '/v1/escrutinio/ambito/')
                    other = self.row(scrutiny_path, params)
                    scrutiny = self.result(other) if other and other['ok'] else {}
                    quality = assess_record({'source': {'params': params}, 'resumen': data,
                                             'escrutinio': scrutiny,
                                             'estado_descarga': 'ok' if row['ok'] and other and other['ok'] else 'incompleto'})
                    sw.writerow({**base, **{k: data.get(k) for k in FIELDS}, **quality})
                else:
                    votes = data.get('votos')
                    if isinstance(votes, list) and votes:
                        for vote in votes:
                            if isinstance(vote, dict):
                                vw.writerow({**base, **{k: vote.get(k) for k in ['conjunto', 'numvotos', 'porcentajeVotos', 'diputados']}})
                    else:
                        vw.writerow(base)

    def run(self, retry_unavailable=False, refresh_catalogs=False):
        self.disk_check()
        if retry_unavailable:
            with self.lock:
                # Attempt history remains intact; only the per-run budget resets.
                self.db.execute('UPDATE responses SET attempts=0,next_retry_at=0 WHERE ok=0')
                self.db.execute('DELETE FROM jobs')
                self.db.execute('DELETE FROM phases')
                self.db.commit()
        (self.out / 'finished.json').unlink(missing_ok=True)
        doc = self.critical('/api-docs', refresh=refresh_catalogs)
        self.paths = {path: methods['get'] for path, methods in doc['paths'].items() if 'get' in methods}
        self.backfill_node_requests()
        atomic_json(self.out / 'api_docs.json', doc)
        self.critical('/v1/opciones/cautonoma', catalog=True, refresh=refresh_catalogs)
        available_types = self.critical('/v1/opciones/tconvocatoria', catalog=True, refresh=refresh_catalogs)
        provinces = self.critical('/v1/opciones/provincia', {'cautonoma': 1}, catalog=True, refresh=refresh_catalogs)
        if {int(p['clave']) for p in provinces} != {4, 11, 14, 18, 21, 23, 29, 41}:
            raise RuntimeError('El catálogo provincial no corresponde a las ocho provincias de Andalucía.')
        elections = []
        for t in SELECTED_TYPES:
            dates = self.critical('/v1/opciones/fconvocatoria', {'tconvocatoria': t}, catalog=True, refresh=refresh_catalogs)
            elections.extend((t, int(entry['clave'])) for entry in sorted(dates, key=lambda x: int(x['clave']), reverse=True))
        atomic_json(self.out / 'plan.json', {
            'created_at': now(), 'api_base': BASE, 'scope': 'Andalucía', 'selected_types': list(SELECTED_TYPES),
            'available_types': available_types, 'elections': elections, 'workers': self.workers,
            'max_requests_per_second': 1/self.interval, 'disk_reserve_bytes': self.reserve,
            'phases': ['core', 'distributions', 'retries', 'final'], 'timeout_seconds': self.timeout,
            'get_templates': sorted(self.paths),
            'excluded_post_converters': [p for p, methods in doc['paths'].items() if 'post' in methods],
            'excluded_reason': 'Conversión de JSON ya disponible a XML, sin nuevos datos de origen.',
            'repo_commit': subprocess.run(['git', '-C', str(PROJECT_ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
            'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'storage': 'SQLite con respuestas exactas comprimidas y hashes; NDJSON y CSV gzip por convocatoria.'})
        # Jobs from the original VPS runner already include all GET views. Adopt
        # their completion checkpoint rather than replaying a finished election.
        with self.lock:
            if not self.db.execute("SELECT 1 FROM archive_meta WHERE key='legacy_jobs_adopted'").fetchone():
                for row in self.db.execute('SELECT t,f FROM jobs').fetchall():
                    for phase in ('core', 'core_export', 'distributions', 'final_export'):
                        self.db.execute('INSERT OR IGNORE INTO phases VALUES(?,?,?,?)', (row['t'], row['f'], phase, now()))
                self.db.execute("INSERT INTO archive_meta VALUES('legacy_jobs_adopted','1')")
                self.db.commit()
        for t, f in elections:
            self.download_core(t, f, provinces)
            if not self.phase_done(t, f, 'core_export'):
                self.export_election(t, f, provinces, stage='core')
        for t, f in elections:
            self.download_distributions(t, f)
        self.retry_pending(elections, provinces)
        for t, f in elections:
            if not self.phase_done(t, f, 'final_export'):
                self.export_election(t, f, provinces)
        self.current = {'state': 'finished', 'phase': 'finished', 'elections': len(elections)}
        self.progress()
        atomic_json(self.out / 'finished.json', {'finished_at': now(), 'elections': elections, **self.totals(),
                                               'note': 'Consultar los manifiestos y los errores de origen en SQLite.'})
        with self.lock:
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def show_status(output):
    path = Path(output) / 'progress.json'
    if not path.exists():
        raise SystemExit(f'No existe un estado guardado: {path}')
    data = json.loads(path.read_text())
    totals = data['totals']
    print(f"Actualizado: {data['updated_at']} | Estado: {data['state']} | Fase: {data.get('phase', 'anterior')}")
    print(f"Convocatoria: tipo {data.get('tconvocatoria', '-')} / {data.get('fconvocatoria', '-')}")
    print(f"Mesas con ambas respuestas: {totals.get('mesas_completed', '?')} / {totals['nodes'].get('mesa', 0)} identificadas")
    print(f"Consultas: {totals['queries']} | Correctas: {totals['ok']} | No disponibles: {totals['source_unavailable']}")
    print(f"Reintentos pendientes: {totals.get('retry_pending', '?')}")
    phases = data.get('phases', [])
    print(f"Convocatorias con datos principales exportados: {sum(p['phase'] == 'core_export' for p in phases)}")
    print(f"Convocatorias finalizadas: {sum(p['phase'] == 'final_export' for p in phases)}")
    for item in data.get('in_flight', []):
        print(f"  Esperando {item['seconds']} s: {item['endpoint']}")
    print('El total identificado crece al descubrir el catálogo; no es un porcentaje del plan completo.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--status', action='store_true', help='Mostrar progreso guardado sin conectar a la API')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--max-rps', type=float, default=6)
    parser.add_argument('--reserve-gib', type=float, default=20)
    parser.add_argument('--timeout', type=float, default=45, help='Espera de lectura HTTP en segundos')
    parser.add_argument('--retry-unavailable', action='store_true')
    parser.add_argument('--refresh-catalogs', action='store_true', help='Actualizar metadatos iniciales y descubrir convocatorias nuevas')
    args = parser.parse_args()
    if (not 1 <= args.workers <= 16 or not all(math.isfinite(x) for x in (args.max_rps, args.reserve_gib, args.timeout))
            or args.max_rps <= 0 or args.reserve_gib < 1 or args.timeout <= 0):
        parser.error('Parámetros de recursos fuera de rango')
    if args.status:
        show_status(args.output)
        return
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True)
    handle = (args.output / '.download.lock').open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Ya hay una descarga utilizando esta carpeta.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    archive = Archive(args.output, args.workers, args.max_rps, args.reserve_gib, timeout=args.timeout)
    signal.signal(signal.SIGTERM, lambda *_: archive.stop.set())
    signal.signal(signal.SIGINT, lambda *_: archive.stop.set())
    heartbeat_stop = threading.Event()
    def heartbeat():
        while not heartbeat_stop.wait(30):
            try:
                archive.progress()
            except Exception:
                logging.exception('No se ha podido actualizar el progreso periódico')
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        archive.run(args.retry_unavailable, args.refresh_catalogs)
    except StopRequested:
        archive.current['state'] = 'stopped'
        archive.progress()
        logging.info('Parada controlada; la próxima ejecución reanudará desde SQLite')
    except BaseException:
        archive.current['state'] = 'failed'
        archive.progress()
        logging.exception('La ejecución se ha detenido; los datos ya archivados se conservan')
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join()
        archive.db.close()


if __name__ == '__main__':
    main()
