"""
Сервер заметок MS2
Запуск: python3 server.py
Доступ из локальной сети: http://<IP-компьютера>:8080
"""
import os, sqlite3, json, secrets, smtplib, threading, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.security import check_password_hash

# ─── Пути ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'notes.db')
PORT     = int(os.environ.get('PORT', 8080))

# ─── Учётные данные ───────────────────────────────────────────────
ADMIN_LOGIN = 'Admin'
ADMIN_PASSWORD_HASH = 'scrypt:32768:8:1$vhYGg11jpZTnbPau$a1b64fdbe4f06df2ec581be642151d68323d7908d19d3b7da498cf6dcb8d572e3186f5dadebbfb5197a291a580760f48f85d2e703f08234421f18bdcb1ae0ad6'

# ─── SMTP (env-переменные используются как значения по умолчанию) ──
SMTP_HOST_DEFAULT = os.environ.get('SMTP_HOST', '')
SMTP_PORT_DEFAULT = os.environ.get('SMTP_PORT', '587')
SMTP_USER_DEFAULT = os.environ.get('SMTP_USER', '')
SMTP_PASS_DEFAULT = os.environ.get('SMTP_PASS', '')

app = Flask(__name__, static_folder=None)

# ─── База данных ───────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS notes (
  id         TEXT PRIMARY KEY,
  content    TEXT    NOT NULL DEFAULT '',
  hashtags   TEXT    NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS filters (
  id     TEXT PRIMARY KEY,
  name   TEXT NOT NULL,
  filter TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mailings (
  id           TEXT PRIMARY KEY,
  name         TEXT    NOT NULL DEFAULT '',
  email        TEXT    NOT NULL DEFAULT '',
  filter1      TEXT    NOT NULL DEFAULT '',
  filter2      TEXT    NOT NULL DEFAULT '',
  filter3      TEXT    NOT NULL DEFAULT '',
  period_days  INTEGER NOT NULL DEFAULT 1,
  last_sent_at INTEGER NOT NULL DEFAULT 0,
  created_at   INTEGER NOT NULL DEFAULT 0
);
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
    print(f"База данных: {DB_PATH}")

# Инициализируем БД при импорте модуля (нужно для gunicorn)
init_db()

# ─── Авторизация ──────────────────────────────────────────────────
def get_token():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None

def is_authenticated():
    token = get_token()
    if not token:
        return False
    with get_db() as conn:
        row = conn.execute('SELECT 1 FROM sessions WHERE token=?', (token,)).fetchone()
    return row is not None

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ─── Хелперы ──────────────────────────────────────────────────────
def note_to_dict(row):
    return {
        'id':        row['id'],
        'content':   row['content'],
        'hashtags':  json.loads(row['hashtags']),
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }

def filter_to_dict(row):
    return {
        'id':     row['id'],
        'name':   row['name'],
        'filter': row['filter'],
    }

def get_smtp_config():
    """Возвращает SMTP-настройки из БД, с fallback на env-переменные."""
    keys = ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass']
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT key, value FROM settings WHERE key IN ({','.join('?'*len(keys))})",
            keys
        ).fetchall()
    cfg = {r['key']: r['value'] for r in rows}
    return {
        'host': cfg.get('smtp_host') or SMTP_HOST_DEFAULT,
        'port': int(cfg.get('smtp_port') or SMTP_PORT_DEFAULT or 587),
        'user': cfg.get('smtp_user') or SMTP_USER_DEFAULT,
        'pass': cfg.get('smtp_pass') or SMTP_PASS_DEFAULT,
    }

def mailing_to_dict(row):
    return {
        'id':          row['id'],
        'name':        row['name'],
        'email':       row['email'],
        'filter1':     row['filter1'],
        'filter2':     row['filter2'],
        'filter3':     row['filter3'],
        'periodDays':  row['period_days'],
        'lastSentAt':  row['last_sent_at'],
        'createdAt':   row['created_at'],
    }

# ─── Логика рассылок ──────────────────────────────────────────────
def hashtag_matches_filter(line, tokens):
    """Проверяет, начинается ли строка хэштегов с заданных токенов."""
    lt = line.strip().split()
    if len(lt) < len(tokens):
        return False
    return all(lt[i].lower() == tokens[i].lower() for i in range(len(tokens)))

def get_notes_for_filter(filter_str):
    """Возвращает заметки, совпадающие с фильтром."""
    tokens = filter_str.strip().split()
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM notes ORDER BY updated_at DESC').fetchall()
    notes = [note_to_dict(r) for r in rows]
    if not tokens:
        return notes
    result = []
    for note in notes:
        if any(hashtag_matches_filter(line, tokens) for line in note['hashtags']):
            result.append(note)
    return result

def build_mailing_html(mailing):
    """Строит HTML-тело письма по данным рассылки."""
    filters = [
        (mailing['filter1'], 'Фильтр 1'),
        (mailing['filter2'], 'Фильтр 2'),
        (mailing['filter3'], 'Фильтр 3'),
    ]
    sections = []
    for flt, label in filters:
        if not flt.strip():
            continue
        notes_list = get_notes_for_filter(flt)
        rows_html = ''
        for n in notes_list:
            tags = '  '.join(n['hashtags'])
            content = (n['content'] or '').replace('\n', '<br>')
            rows_html += f'''
              <tr>
                <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:14px;color:#1a1d21;">{content}</td>
                <td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:12px;color:#1a73e8;font-family:monospace;white-space:nowrap;">{tags}</td>
              </tr>'''
        count = len(notes_list)
        sections.append(f'''
          <h3 style="margin:24px 0 8px;font-size:15px;color:#5f6368;">
            {label}: <code style="background:#f0f2f5;padding:2px 6px;border-radius:4px;">{flt}</code>
            &nbsp;<span style="font-size:13px;color:#9aa0a6;">({count} шт.)</span>
          </h3>
          <table style="width:100%;border-collapse:collapse;border:1px solid #dde1e7;border-radius:8px;overflow:hidden;">
            <thead>
              <tr style="background:#f8f9fa;">
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#9aa0a6;font-weight:600;">Заметка</th>
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#9aa0a6;font-weight:600;">Параметры</th>
              </tr>
            </thead>
            <tbody>{rows_html if rows_html else "<tr><td colspan='2' style='padding:10px 12px;color:#9aa0a6;font-size:13px;'>Нет заметок</td></tr>"}</tbody>
          </table>''')

    body = '\n'.join(sections) if sections else '<p style="color:#9aa0a6;">Фильтры не заданы</p>'
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:system-ui,-apple-system,sans-serif;margin:0;padding:20px;background:#f0f2f5;">
  <div style="max-width:700px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;border:1px solid #dde1e7;">
    <h2 style="margin:0 0 4px;font-size:18px;color:#1a1d21;">{mailing['name']}</h2>
    <p style="margin:0 0 20px;font-size:13px;color:#9aa0a6;">Рассылка MS2</p>
    {body}
  </div>
</body>
</html>'''

def send_mailing_email(mailing):
    """Отправляет письмо рассылки. Возвращает None или строку с ошибкой."""
    smtp = get_smtp_config()
    if not smtp['host'] or not smtp['user'] or not smtp['pass']:
        return 'SMTP не настроен. Перейдите в Настройки → Настройка почты'
    recipient = mailing['email'].strip()
    if not recipient:
        return 'Адрес получателя не указан'
    html = build_mailing_html(mailing)
    msg = MIMEMultipart('alternative')
    msg['From']    = smtp['user']
    msg['To']      = recipient
    msg['Subject'] = f'Рассылка: {mailing["name"]}'
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        with smtplib.SMTP(smtp['host'], smtp['port']) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp['user'], smtp['pass'])
            server.send_message(msg)
        return None
    except Exception as e:
        return str(e)

# ─── Планировщик рассылок (фоновый поток) ─────────────────────────
def mailing_scheduler():
    """Каждую минуту проверяет, не пора ли отправить рассылку (в 9:00 местного времени)."""
    import datetime
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == 9 and now.minute == 0:
                today_day = int(time.time()) // 86400
                with get_db() as conn:
                    rows = conn.execute('SELECT * FROM mailings').fetchall()
                for row in rows:
                    m = mailing_to_dict(row)
                    last_day = m['lastSentAt'] // 86400 if m['lastSentAt'] else 0
                    days_passed = today_day - last_day
                    if days_passed >= m['periodDays']:
                        err = send_mailing_email(m)
                        if not err:
                            with get_db() as conn:
                                conn.execute(
                                    'UPDATE mailings SET last_sent_at=? WHERE id=?',
                                    (int(time.time()), m['id'])
                                )
        except Exception:
            pass
        time.sleep(60)

# ─── HTML ─────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

# ─── API: Вход / Выход ────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    login_in = data.get('login', '')
    password = data.get('password', '')
    if login_in == ADMIN_LOGIN and check_password_hash(ADMIN_PASSWORD_HASH, password):
        token = secrets.token_hex(32)
        with get_db() as conn:
            conn.execute('INSERT INTO sessions (token, created_at) VALUES (?, ?)',
                         (token, int(time.time())))
        return jsonify({'token': token})
    return jsonify({'error': 'Неверный логин или пароль'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    token = get_token()
    if token:
        with get_db() as conn:
            conn.execute('DELETE FROM sessions WHERE token=?', (token,))
    return jsonify({'ok': True})

# ─── API: Заметки ─────────────────────────────────────────────────
@app.route('/api/notes', methods=['GET'])
@require_auth
def get_notes():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM notes ORDER BY updated_at DESC'
        ).fetchall()
    return jsonify([note_to_dict(r) for r in rows])


@app.route('/api/notes', methods=['POST'])
@require_auth
def create_note():
    data = request.get_json()
    with get_db() as conn:
        conn.execute(
            'INSERT INTO notes (id, content, hashtags, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (data['id'], data.get('content', ''),
             json.dumps(data.get('hashtags', []), ensure_ascii=False),
             data['createdAt'], data['updatedAt'])
        )
    return jsonify({'ok': True}), 201


@app.route('/api/notes/<note_id>', methods=['PUT'])
@require_auth
def update_note(note_id):
    data = request.get_json()
    with get_db() as conn:
        conn.execute(
            'UPDATE notes SET content=?, hashtags=?, updated_at=? WHERE id=?',
            (data.get('content', ''),
             json.dumps(data.get('hashtags', []), ensure_ascii=False),
             data['updatedAt'], note_id)
        )
    return jsonify({'ok': True})


@app.route('/api/notes/<note_id>', methods=['DELETE'])
@require_auth
def delete_note(note_id):
    with get_db() as conn:
        conn.execute('DELETE FROM notes WHERE id=?', (note_id,))
    return jsonify({'ok': True})

# ─── API: Фильтры ─────────────────────────────────────────────────
@app.route('/api/filters', methods=['GET'])
@require_auth
def get_filters():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM filters').fetchall()
    return jsonify([filter_to_dict(r) for r in rows])


@app.route('/api/filters', methods=['POST'])
@require_auth
def save_filter():
    data = request.get_json()
    with get_db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO filters (id, name, filter) VALUES (?, ?, ?)',
            (data['id'], data['name'], data['filter'])
        )
    return jsonify({'ok': True}), 201


@app.route('/api/filters/<filter_id>', methods=['DELETE'])
@require_auth
def delete_filter(filter_id):
    with get_db() as conn:
        conn.execute('DELETE FROM filters WHERE id=?', (filter_id,))
    return jsonify({'ok': True})

# ─── API: Рассылки ────────────────────────────────────────────────
@app.route('/api/mailings', methods=['GET'])
@require_auth
def get_mailings():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM mailings ORDER BY created_at DESC').fetchall()
    return jsonify([mailing_to_dict(r) for r in rows])


@app.route('/api/mailings', methods=['POST'])
@require_auth
def save_mailing():
    data = request.get_json() or {}
    mid = data.get('id') or secrets.token_hex(8)
    now = int(time.time())
    with get_db() as conn:
        existing = conn.execute('SELECT id FROM mailings WHERE id=?', (mid,)).fetchone()
        if existing:
            conn.execute(
                'UPDATE mailings SET name=?,email=?,filter1=?,filter2=?,filter3=?,period_days=? WHERE id=?',
                (data.get('name',''), data.get('email',''),
                 data.get('filter1',''), data.get('filter2',''), data.get('filter3',''),
                 int(data.get('periodDays', 1)), mid)
            )
        else:
            conn.execute(
                'INSERT INTO mailings (id,name,email,filter1,filter2,filter3,period_days,last_sent_at,created_at) '
                'VALUES (?,?,?,?,?,?,?,0,?)',
                (mid, data.get('name',''), data.get('email',''),
                 data.get('filter1',''), data.get('filter2',''), data.get('filter3',''),
                 int(data.get('periodDays', 1)), now)
            )
    with get_db() as conn:
        row = conn.execute('SELECT * FROM mailings WHERE id=?', (mid,)).fetchone()
    return jsonify(mailing_to_dict(row)), 201


@app.route('/api/mailings/<mailing_id>', methods=['DELETE'])
@require_auth
def delete_mailing(mailing_id):
    with get_db() as conn:
        conn.execute('DELETE FROM mailings WHERE id=?', (mailing_id,))
    return jsonify({'ok': True})


@app.route('/api/mailings/<mailing_id>/test', methods=['POST'])
@require_auth
def test_mailing(mailing_id):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM mailings WHERE id=?', (mailing_id,)).fetchone()
    if not row:
        return jsonify({'error': 'Рассылка не найдена'}), 404
    m = mailing_to_dict(row)
    err = send_mailing_email(m)
    if err:
        return jsonify({'error': err}), 500
    return jsonify({'ok': True})

# ─── API: Настройки SMTP ──────────────────────────────────────────
@app.route('/api/settings/smtp', methods=['GET'])
@require_auth
def get_smtp_settings():
    smtp = get_smtp_config()
    # Не возвращаем пароль в открытом виде — только маску
    return jsonify({
        'host': smtp['host'],
        'port': smtp['port'],
        'user': smtp['user'],
        'hasPass': bool(smtp['pass']),
    })


@app.route('/api/settings/smtp', methods=['POST'])
@require_auth
def save_smtp_settings():
    data = request.get_json() or {}
    pairs = [
        ('smtp_host', data.get('host', '').strip()),
        ('smtp_port', str(data.get('port', 587))),
        ('smtp_user', data.get('user', '').strip()),
    ]
    # Пароль обновляем только если передан непустой
    if data.get('pass', '').strip():
        pairs.append(('smtp_pass', data['pass'].strip()))
    with get_db() as conn:
        for key, value in pairs:
            conn.execute(
                'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                (key, value)
            )
    return jsonify({'ok': True})


@app.route('/api/settings/smtp/test', methods=['POST'])
@require_auth
def test_smtp_settings():
    data = request.get_json() or {}
    smtp = get_smtp_config()
    # Если переданы временные параметры — использовать их
    host = data.get('host', '').strip() or smtp['host']
    port = int(data.get('port', 0) or smtp['port'])
    user = data.get('user', '').strip() or smtp['user']
    pwd  = data.get('pass', '').strip() or smtp['pass']
    to   = data.get('to', '').strip() or user
    if not host or not user or not pwd:
        return jsonify({'error': 'SMTP не настроен'}), 400
    if not to:
        return jsonify({'error': 'Укажите адрес получателя'}), 400
    msg = MIMEMultipart('alternative')
    msg['From']    = user
    msg['To']      = to
    msg['Subject'] = 'Тест SMTP — MS2'
    msg.attach(MIMEText('<p>Тестовое письмо от MS2. SMTP работает корректно.</p>', 'html', 'utf-8'))
    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Запуск ───────────────────────────────────────────────────────
if __name__ == '__main__':
    import socket
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = '127.0.0.1'

    t = threading.Thread(target=mailing_scheduler, daemon=True)
    t.start()

    print(f"\n{'='*45}")
    print(f"  Сервер MS2 запущен")
    print(f"{'='*45}")
    print(f"  Этот компьютер:  http://localhost:{PORT}")
    print(f"  Локальная сеть:  http://{local_ip}:{PORT}")
    print(f"{'='*45}\n")

    app.run(host='0.0.0.0', port=PORT, debug=False)
