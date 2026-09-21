"""Observable local background jobs. Events reflect actual processing boundaries."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from . import repository as repo

POOL=ThreadPoolExecutor(max_workers=2)
ACTIVE=set()
LOCK=threading.RLock()

def update(jid,**changes):
    with LOCK,repo.connect() as db:
        row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row:raise KeyError('Processing job not found')
        job=json.loads(row['data']);job.update(changes)
        db.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(job),jid))
    return job

def progress(jid,vid,stage,message):
    if not jid:return
    with LOCK,repo.connect() as db:
        row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
        job=json.loads(row['data'])
        job['vendors'][vid]={'stage':stage,'message':message,'at':repo.now()}
        job['events'].append({'vendor_id':vid,'stage':stage,'message':message,'at':repo.now()})
        db.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(job),jid))

def read(jid):
    with repo.connect() as db:
        row=db.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row:raise KeyError('Processing job not found')
        job=json.loads(row['data'])
    if job['status']=='running' and jid not in ACTIVE:
        job=update(jid,status='interrupted',error='The app restarted during processing. Retry to resume from saved results.')
    return job

def start():
    from . import graph
    d=repo.read()
    if d['rfx_status']!='approved':raise ValueError('Approve the RFx first.')
    if not any(v.get('documents') for v in d['vendors'].values()):raise ValueError('Receive at least one supplier message or attachment first.')
    with LOCK:
        if ACTIVE:raise ValueError('A processing run is already active. Follow its progress below.')
        jid=str(uuid4());job={'id':jid,'created':repo.now(),'status':'running','vendors':{},'events':[],'error':None}
        with repo.connect() as db:db.execute('INSERT INTO jobs VALUES(?,?,?)',(jid,job['created'],json.dumps(job)))
        ACTIVE.add(jid)
    def work():
        try:
            result=graph.run('process',job_id=jid)
            update(jid,status='completed',workflow=result)
        except Exception as exc:
            # Never serialize request objects, credential headers or provider response bodies.
            message=str(exc) if isinstance(exc,(ValueError,RuntimeError,KeyError)) else 'Unable to process a source document. Check its format and retry.'
            import traceback
            # Location and exception type only: never log provider payloads or secrets.
            frames=traceback.extract_tb(exc.__traceback__)
            location=frames[-1] if frames else None
            diagnostic={'type':type(exc).__name__,'file':location.filename.rsplit('/',1)[-1] if location else None,'line':location.lineno if location else None}
            update(jid,status='failed',error=message,diagnostic=diagnostic)
        finally:
            with LOCK:ACTIVE.discard(jid)
    POOL.submit(work)
    return job
