#!/usr/bin/env python3
"""Generate the static download page from the published release catalogue."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def number(value):
    return f'{value:,}'.replace(',', '.')


def size(value):
    return f'{value / 1_000_000:.1f}'.replace('.', ',') + ' MB'


def build():
    catalog = json.loads((ROOT / 'docs/catalogo.json').read_text())
    esc = html.escape
    rows = []
    for entry in catalog['elections']:
        badges = ''.join(f'<span class="badge {state}">{number(entry["quality"][state])} {label[:-1] if entry["quality"][state] == 1 and state != "ok" else label}</span>'
                         for state, label in [('ok', 'sin incidencias detectadas'), ('inconsistente', 'inconsistentes'), ('incompleto', 'incompletas')]
                         if entry['quality'].get(state))
        rows.append(f'''<article class="election" aria-labelledby="e{entry['date']}">
          <div><h3 id="e{entry['date']}">{entry['year']}</h3><p class="date">{esc(entry['label'])}</p></div>
          <div class="tables"><strong>{number(entry['tables'])}</strong><span> mesas catalogadas</span></div>
          <div class="badges">{badges}</div>
          <a class="download" href="{esc(entry['url'])}" aria-label="Descargar elección de {entry['year']} en ZIP">Descargar ZIP <span>↓ &nbsp; {size(entry['bytes'])}</span></a>
        </article>''')
    page = (ROOT / 'docs/index.template.html').read_text()
    replacements = {'ALL_URL': esc(catalog['all']['url']), 'ALL_SIZE': size(catalog['all']['bytes']),
                    'TOTAL': number(sum(x['tables'] for x in catalog['elections'])), 'ROWS': '\n'.join(rows),
                    'RELEASE': esc(catalog['release_url']), 'VERSION': esc(catalog['version'])}
    for key, value in replacements.items():
        page = page.replace('{{' + key + '}}', value)
    (ROOT / 'docs/index.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    build()
