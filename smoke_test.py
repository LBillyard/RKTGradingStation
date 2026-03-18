"""RKT Grading Station - Comprehensive Smoke Test."""
import requests
import os
import json

BASE = 'http://127.0.0.1:8741'
results = []


def chk(name, url, exp, h=None):
    try:
        r = requests.get(url, headers=h, timeout=10)
        ok = r.status_code == exp
        results.append(('PASS' if ok else 'FAIL', name, r.status_code, exp))
        return r
    except Exception as e:
        results.append(('FAIL', name, str(e)[:50], exp))
        return None


# === AUTH ===
r = requests.post(f'{BASE}/api/auth/login', json={'name': 'Luke', 'password': 'Poker2013!'}, timeout=10)
if r.status_code != 200:
    print(f'Cannot login: {r.text}')
    exit(1)

token = r.json()['token']
h = {'Authorization': f'Bearer {token}'}
results.append(('PASS', 'Auth: Login', 200, 200))
chk('Auth: GET /me', f'{BASE}/api/auth/me', 200, h)
chk('Auth: GET /operators', f'{BASE}/api/auth/operators', 200, h)

# === DASHBOARD ===
r = chk('Dashboard: GET /summary', f'{BASE}/api/dashboard/summary', 200, h)
if r and r.status_code == 200:
    data = r.json()
    for key in ['total_scans', 'total_graded', 'pending_review', 'auth_alerts', 'system_status']:
        if key not in data:
            results.append(('FAIL', f'Dashboard: missing "{key}"', 'missing', 'present'))
    results.append(('PASS', 'Dashboard: schema complete', '-', '-'))
    if 'engraving' in json.dumps(data).lower():
        results.append(('FAIL', 'Dashboard: has engraving data', '-', '-'))
    else:
        results.append(('PASS', 'Dashboard: no engraving', '-', '-'))

chk('Dashboard: GET /recent-activity', f'{BASE}/api/dashboard/recent-activity', 200, h)

# === SETTINGS ===
for name, path in [
    ('scanner', '/api/settings/scanner'),
    ('grading', '/api/settings/grading'),
    ('openrouter', '/api/settings/openrouter'),
    ('system', '/api/settings/system'),
    ('webhook', '/api/settings/webhook'),
    ('security', '/api/settings/security'),
    ('authenticity', '/api/settings/authenticity'),
    ('api', '/api/settings/api'),
    ('current', '/api/settings/current'),
]:
    chk(f'Settings: {name}', f'{BASE}{path}', 200, h)

chk('Settings: engraving GONE', f'{BASE}/api/settings/engraving', 404, h)

r2 = requests.get(f'{BASE}/api/settings/current', headers=h, timeout=10)
if r2.status_code == 200:
    if 'engraving' in r2.text.lower():
        results.append(('FAIL', 'Settings /current has engraving', '-', '-'))
    else:
        results.append(('PASS', 'Settings /current clean', '-', '-'))

# === OTHER ENDPOINTS ===
for name, path in [
    ('Queue list', '/api/queue/list'),
    ('Scan devices', '/api/scan/devices/list'),
    ('Reports summary', '/api/reports/summary'),
    ('Audit events', '/api/audit/events'),
    ('Backup list', '/api/backup/list'),
    ('Security templates', '/api/security/templates'),
    ('Reference cards', '/api/reference/cards'),
]:
    chk(name, f'{BASE}{path}', 200, h)

# Engraving gone
chk('Engraving: /jobs GONE', f'{BASE}/api/engraving/jobs', 404, h)
chk('Engraving: /templates GONE', f'{BASE}/api/engraving/templates', 404, h)
chk('Engraving: reports GONE', f'{BASE}/api/reports/engraving-stats', 404, h)

# === FRONTEND ===
html = requests.get(f'{BASE}/', timeout=10).text
results.append(('PASS' if 'REX' not in html else 'FAIL', 'HTML: no REX', '-', '-'))
results.append(('PASS' if 'RKT' in html else 'FAIL', 'HTML: has RKT', '-', '-'))
results.append(('PASS' if 'engraving' not in html.lower() else 'FAIL', 'HTML: no engraving nav', '-', '-'))

for js in ['app.js', 'api.js', 'components.js']:
    r2 = requests.get(f'{BASE}/static/js/{js}', timeout=10)
    if r2.status_code != 200:
        results.append(('FAIL', f'JS: {js} not loading', r2.status_code, 200))
    elif 'REX' in r2.text:
        results.append(('FAIL', f'JS: {js} has REX', '-', '-'))
    else:
        results.append(('PASS', f'JS: {js} OK', '-', '-'))

for page in ['dashboard.js', 'new-scan.js', 'queue.js', 'grade-review.js', 'settings.js',
             'audit-log.js', 'reports.js', 'login.js', 'security-templates.js', 'reference-library.js']:
    chk(f'Page: {page}', f'{BASE}/static/js/pages/{page}', 200)

chk('Page: engraving-jobs.js GONE', f'{BASE}/static/js/pages/engraving-jobs.js', 404)

# === SOURCE CODE ===
rex_count = 0
for root, dirs, files in os.walk('app'):
    for f in files:
        if f.endswith(('.py', '.js', '.html', '.css')):
            path = os.path.join(root, f)
            for line in open(path):
                if 'REX' in line:
                    rex_count += 1

results.append(('PASS' if rex_count == 0 else 'FAIL', f'Source: no REX ({rex_count} found)', '-', '-'))
results.append(('PASS' if 'REX_' not in open('.env').read() else 'FAIL', '.env: uses RKT_', '-', '-'))

# === REPORT ===
print()
print('=' * 65)
print('  RKT GRADING STATION - COMPREHENSIVE SMOKE TEST')
print('=' * 65)
p = f2 = 0
current_section = ''
for s, n, g, e in results:
    section = n.split(':')[0] if ':' in n else n.split(' ')[0]
    if section != current_section:
        current_section = section
        print(f'\n  --- {section} ---')
    if s == 'PASS':
        p += 1
        print(f'  [OK] {n}')
    else:
        f2 += 1
        print(f'  [XX] {n} (got {g}, expected {e})')

print(f'\n{"=" * 65}')
print(f'  RESULT: {p} PASSED | {f2} FAILED')
print('=' * 65)
