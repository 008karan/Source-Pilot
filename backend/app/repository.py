"""SQLite business storage: immutable complete snapshots + append-only audit/scenarios.

Snapshots deliberately keep source facts, evidence and derived facts together so a
historical scenario is reproducible. LangGraph uses its own checkpoint database.
"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .store import DATA_DIR, ROOT

LOCK = threading.RLock()
VENDORS = {
    'packright': ('PackRight Industries', 'vendor_a_packright_offer.xlsx'),
    'corrpro': ('CorrPro International', 'vendor_b_corrpro_quote.pdf'),
    'boxworks': ('BoxWorks India Pvt Ltd', 'vendor_c_boxworks_offer.docx'),
    'alphapack': ('AlphaPack Solutions', 'vendor_d_alphapack_rate_card_photo.jpg'),
    'greencarton': ('GreenCarton Co.', 'vendor_e_greencarton_reply.eml'),
}

def now():
    return datetime.now(timezone.utc).isoformat()

def new_vendor(vid,name,email=''):
    return {'id':vid,'name':name,'email':email,'file':'','format':'proposal','quality':'pending','lead':None,'response_status':'awaiting_ingestion','facts':[],'terms':{},'questionnaire':{},'lines':[],'documents':[],'message':''}

def runtime_dir():
    p = Path(os.getenv('AERCHAIN_DATA_DIR', str(ROOT / 'runtime')))
    p.mkdir(parents=True, exist_ok=True)
    return p

@contextmanager
def connect():
    with LOCK:
        db = sqlite3.connect(runtime_dir() / 'business.sqlite', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS datasets(version INTEGER PRIMARY KEY, created TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY, created TEXT, actor TEXT, action TEXT, version INTEGER, detail TEXT);
          CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, created TEXT, version INTEGER, data TEXT);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created TEXT, updated TEXT, data TEXT);
        ''')
        try:
            yield db
            db.commit()
        finally:
            db.close()

def blank_rfx():
    """A first open starts on an empty request: no event, no lines, no suppliers."""
    return {'event_id': 'RFQ-' + uuid4().hex[:8].upper(), 'title': '', 'category': '', 'buyer': 'Priya Menon',
            'currency': 'INR', 'comparison_uom': 'piece', 'bid_due_date': '', 'expected_annual_spend_inr': 0,
            'scope': '', 'baseline_available': False,
            'commercial_rules': {'comparison_basis': 'landed_cost_excluding_gst', 'fx_rate_usd_inr': 83.2,
                                 'freight_required': True, 'gst_excluded_from_comparison': True,
                                 'quote_validity_days': 60},
            'items': [], 'questionnaire': []}

def demo_rfx():
    """The bundled 30-line packaging brief, loaded only when the buyer picks the example."""
    return json.loads((DATA_DIR / 'rfx.json').read_text())

def demo_vendors():
    return {v: {'id':v, 'name': n, 'file': f, 'format':Path(f).suffix[1:],
                'quality':'pending', 'lead':None, 'response_status':'awaiting_ingestion',
                'facts':[], 'terms':{}, 'questionnaire':{}, 'lines':[], 'documents':[],'message':''}
            for v,(n,f) in VENDORS.items()}

def demo_offers_match(rfx):
    """The bundled supplier offers quote these exact SKUs, so they fit any event
    that lists the same ones — however that event was created."""
    lines = (rfx or {}).get('items') or []
    expected = demo_rfx()['items']
    if len(lines) != len(expected):
        return False
    return all(item['sku'] == line.get('sku') or item['sku'] in str(line.get('description') or '')
               for item, line in zip(expected, lines))

def initial():
    return {'dataset_version': 1, 'rfx': blank_rfx(), 'rfx_status': 'draft', 'rfx_version': 1,
            'draft': None, 'workflow_id': None, 'stage': 'draft', 'vendors': {}, 'evidence':{}, 'comparison':[],
            'exceptions':[], 'clarifications':[]}

def read(version=None):
    with connect() as db:
        row = db.execute('SELECT data FROM datasets WHERE version=?', (version,)).fetchone() if version else db.execute('SELECT data FROM datasets ORDER BY version DESC LIMIT 1').fetchone()
        if row:
            return json.loads(row['data'])
        if version is not None:
            raise KeyError('Dataset version not found')
        data = initial()
        db.execute('INSERT INTO datasets VALUES(?,?,?)', (1, now(), json.dumps(data)))
        return data

def change(action, actor, mutate, expected=None):
    with LOCK:
        data = read()
        if expected is not None and data['dataset_version'] != expected:
            raise ValueError('This dataset changed. Refresh before saving your correction.')
        mutate(data)
        data['dataset_version'] += 1
        with connect() as db:
            db.execute('INSERT INTO datasets VALUES(?,?,?)', (data['dataset_version'], now(), json.dumps(data, allow_nan=False)))
            db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (str(uuid4()), now(), actor, action, data['dataset_version'], json.dumps({'action':action})))
        return data

def save_scenario(result, question='', interpreter='structured_form'):
    result = dict(result, id=str(uuid4()), created_at=now(), question=question, interpreter=interpreter)
    with connect() as db:
        db.execute('INSERT INTO scenarios VALUES(?,?,?,?)', (result['id'], result['created_at'], result['dataset_version'], json.dumps(result)))
    return dict(result, stale=result['dataset_version'] != read()['dataset_version'])

def scenarios():
    current = read()['dataset_version']
    with connect() as db:
        return [dict(json.loads(r['data']), stale=r['version'] != current) for r in db.execute('SELECT * FROM scenarios ORDER BY created DESC')]

def scenario(sid):
    for s in scenarios():
        if s['id'] == sid:
            return s
    raise KeyError('Scenario not found')

def session(session_id):
    """Every turn of one conversation, oldest first."""
    with connect() as db:
        row = db.execute('SELECT data FROM sessions WHERE id=?', (session_id,)).fetchone()
        return json.loads(row['data']) if row else []

def log_turn(session_id, turn):
    """Append a turn. The log is the conversation's memory, not the browser."""
    with LOCK:
        turns = session(session_id)[-39:] + [dict(turn, at=now())]
        with connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=?, data=?',
                       (session_id, now(), now(), json.dumps(turns), now(), json.dumps(turns)))
        return turns

def sessions(limit=20):
    with connect() as db:
        return [{'id': r['id'], 'created': r['created'], 'updated': r['updated'],
                 'turns': len(json.loads(r['data']))}
                for r in db.execute('SELECT * FROM sessions ORDER BY updated DESC LIMIT ?', (limit,))]

def audit():
    with connect() as db:
        return [dict(x) for x in db.execute('SELECT * FROM audit ORDER BY created DESC')]
