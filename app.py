"""
CallUSSD Backend — Flask API
Deploy on Render (free tier). See .env.example for all environment variables.
Run locally:  pip install -r requirements.txt && python app.py
"""
import os
import json
import sqlite3
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Optional Twilio VoIP (in-browser calling). Leave env vars blank to disable.
TWILIO_ENABLED = bool(os.environ.get('TWILIO_ACCOUNT_SID'))
if TWILIO_ENABLED:
    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant
    from twilio.twiml.voice_response import VoiceResponse, Dial

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['AUTH_TOKEN'] = os.environ.get('AUTH_TOKEN', '')  # blank = open access

# CORS — restrict to your frontend URL in production via CORS_ORIGINS
_origins = os.environ.get('CORS_ORIGINS', '*')
CORS(app, resources={r"/api/*": {"origins": _origins.split(',') if _origins != '*' else '*'}})

DB_PATH = os.environ.get('DATABASE_PATH', 'callussd.db')
DATABASE_URL = os.environ.get('DATABASE_URL', '')


# ---------- Database ----------
def get_db():
    if 'db' not in g:
        if DATABASE_URL and DATABASE_URL.startswith('postgres'):
            # Use psycopg2 if Postgres URL provided (Render Postgres)
            import psycopg2
            from psycopg2.extras import RealDictCursor
            g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            g.pg = True
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.pg = False
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't exist."""
    if DATABASE_URL and DATABASE_URL.startswith('postgres'):
        conn = None
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY, device_id TEXT, name TEXT, phone TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS call_log (
                id SERIAL PRIMARY KEY, device_id TEXT, number TEXT, type TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW())""")
            conn.commit()
        finally:
            if conn: conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, name TEXT, phone TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS call_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, number TEXT, type TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        conn.commit()
        conn.close()


# ---------- Auth (optional token) ----------
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = app.config['AUTH_TOKEN']
        if token:
            supplied = request.headers.get('X-Auth-Token', '') or request.args.get('token', '')
            if not secrets.compare_digest(supplied, token):
                return jsonify({'error': 'Unauthorized. Set X-Auth-Token header.'}), 401
        return f(*args, **kwargs)
    return wrapper


def get_device_id():
    return request.headers.get('X-Device-Id', 'anonymous')


# ---------- USSD Catalog (editable server-side) ----------
USSD_CATALOG = [
    {"name": "Access Bank", "code": "*901#", "desc": "Account balance, transfer, airtime"},
    {"name": "GTBank", "code": "*737#", "desc": "Transfer, airtime, account opening"},
    {"name": "First Bank", "code": "*894#", "desc": "Quick banking services"},
    {"name": "UBA", "code": "*919#", "desc": "Transfer, bills, airtime"},
    {"name": "Zenith Bank", "code": "*966#", "desc": "Eazymoney banking"},
    {"name": "Ecobank", "code": "*326#", "desc": "Ecobank mobile banking"},
    {"name": "Fidelity Bank", "code": "*770#", "desc": "Instant banking"},
    {"name": "Stanbic IBTC", "code": "*909#", "desc": "Mobile money services"},
    {"name": "Sterling Bank", "code": "*822#", "desc": "Sterling OnePay"},
    {"name": "Union Bank", "code": "*826#", "desc": "UnionMobile USSD"},
    {"name": "Wema Bank", "code": "*945#", "desc": "ALAT banking"},
    {"name": "Polaris Bank", "code": "*833#", "desc": "Polaris mobile"},
    {"name": "FCMB", "code": "*329#", "desc": "FCMB mobile"},
    {"name": "Kuda Bank", "code": "*5115#", "desc": "Kuda USSD banking"},
    {"name": "Opay", "code": "*955#", "desc": "Opay mobile money"},
    {"name": "Palmpay", "code": "*652#", "desc": "Palmpay services"},
    {"name": "Check BVN (All Networks)", "code": "*565*0#", "desc": "NIBSS BVN check (N20 fee)"},
    {"name": "Check NIN", "code": "*346#", "desc": "Verify your National ID"},
]


# ---------- Routes ----------
@app.route('/')
def index():
    return jsonify({
        'app': 'CallUSSD Backend',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': ['/api/health', '/api/ussd/catalog', '/api/contacts/sync', '/api/contacts', '/api/log']
    })


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.now(timezone.utc).isoformat()})


@app.route('/api/ussd/catalog')
def ussd_catalog():
    return jsonify({'count': len(USSD_CATALOG), 'codes': USSD_CATALOG})


@app.route('/api/contacts/sync', methods=['POST'])
@require_auth
def sync_contacts():
    """Upsert contacts for a device (backup)."""
    data = request.get_json(force=True, silent=True) or {}
    contacts = data.get('contacts', [])
    device_id = get_device_id()
    db = get_db()
    cur = db.cursor()
    if g.pg:
        cur.execute("DELETE FROM contacts WHERE device_id = %s", (device_id,))
        for c in contacts:
            cur.execute("INSERT INTO contacts (device_id, name, phone) VALUES (%s, %s, %s)",
                        (device_id, c.get('name', ''), c.get('phone', '')))
    else:
        cur.execute("DELETE FROM contacts WHERE device_id = ?", (device_id,))
        for c in contacts:
            cur.execute("INSERT INTO contacts (device_id, name, phone) VALUES (?, ?, ?)",
                        (device_id, c.get('name', ''), c.get('phone', '')))
    db.commit()
    return jsonify({'status': 'synced', 'count': len(contacts), 'device_id': device_id})


@app.route('/api/contacts', methods=['GET'])
@require_auth
def get_contacts():
    """Restore contacts for a device."""
    device_id = get_device_id()
    db = get_db()
    cur = db.cursor()
    if g.pg:
        cur.execute("SELECT name, phone FROM contacts WHERE device_id = %s ORDER BY name", (device_id,))
    else:
        cur.execute("SELECT name, phone FROM contacts WHERE device_id = ? ORDER BY name", (device_id,))
    rows = cur.fetchall()
    contacts = [{'name': r['name'], 'phone': r['phone']} for r in rows]
    return jsonify({'contacts': contacts, 'count': len(contacts)})


@app.route('/api/log', methods=['POST'])
@require_auth
def add_log():
    data = request.get_json(force=True, silent=True) or {}
    device_id = get_device_id()
    db = get_db()
    cur = db.cursor()
    if g.pg:
        cur.execute("INSERT INTO call_log (device_id, number, type) VALUES (%s, %s, %s)",
                    (device_id, data.get('number', ''), data.get('type', 'call')))
    else:
        cur.execute("INSERT INTO call_log (device_id, number, type) VALUES (?, ?, ?)",
                    (device_id, data.get('number', ''), data.get('type', 'call')))
    db.commit()
    return jsonify({'status': 'logged'})


@app.route('/api/log', methods=['GET'])
@require_auth
def get_log():
    device_id = get_device_id()
    db = get_db()
    cur = db.cursor()
    if g.pg:
        cur.execute("SELECT number, type, created_at FROM call_log WHERE device_id = %s ORDER BY created_at DESC LIMIT 100", (device_id,))
    else:
        cur.execute("SELECT number, type, created_at FROM call_log WHERE device_id = ? ORDER BY created_at DESC LIMIT 100", (device_id,))
    rows = cur.fetchall()
    return jsonify({'log': [dict(r) for r in rows]})


# ---------- Twilio VoIP (in-browser calling, optional) ----------
@app.route('/api/twilio/status')
def twilio_status():
    return jsonify({'enabled': TWILIO_ENABLED})


@app.route('/api/twilio/token')
@require_auth
def twilio_token():
    """Return a Twilio access token so the browser can make VoIP calls."""
    if not TWILIO_ENABLED:
        return jsonify({'error': 'Twilio not configured. Set TWILIO_* env vars.'}), 503
    account_sid = os.environ['TWILIO_ACCOUNT_SID']
    api_key = os.environ['TWILIO_API_KEY']
    api_secret = os.environ['TWILIO_API_SECRET']
    twiml_app_sid = os.environ['TWILIO_APP_SID']
    identity = request.args.get('identity', 'callussd-user')
    token = AccessToken(account_sid, api_key, api_secret, identity=identity)
    token.add_grant(VoiceGrant(outgoing_application_sid=twiml_app_sid))
    return jsonify({'token': token.to_jwt(), 'identity': identity})


@app.route('/api/twilio/voice', methods=['POST', 'GET'])
def twilio_voice():
    """TwiML webhook — tells Twilio what to do when the browser calls out."""
    if not TWILIO_ENABLED:
        return Response('<Response><Say>Twilio is not configured.</Say></Response>',
                        mimetype='application/xml', status=503)
    resp = VoiceResponse()
    to = request.values.get('To')
    caller_id = os.environ.get('TWILIO_CALLER_ID', '')
    if to and to.startswith('client:'):
        dial = Dial()
        dial.client(to[7:])
        resp.append(dial)
    elif to:
        dial = Dial(callerId=caller_id)
        dial.number(to)
        resp.append(dial)
    else:
        resp.say('Thanks for using CallUSSD.')
    return Response(str(resp), mimetype='application/xml')


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


# Initialize DB before first request
with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')
