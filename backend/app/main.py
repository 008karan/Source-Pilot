from __future__ import annotations
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict
from . import repository as repo, pipeline, graph, jobs, intake, intake_docs, insights, knowledge, dossier
from .ai import draft_rfx, has_ai, interpret_scenario, ai_extract_text, transcribe_audio, MODEL
from .scenario import solve_scenario, ValidatedSpec
from .store import ROOT, DATA_DIR

app=FastAPI(title='Aerchain Sourcing Decision Room',version='1.0.0')
app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')

@app.exception_handler(ValueError)
async def bad_value(request,exc):return JSONResponse(status_code=422,content={'detail':str(exc)})
@app.exception_handler(KeyError)
async def not_found(request,exc):return JSONResponse(status_code=404,content={'detail':str(exc)})
@app.exception_handler(RuntimeError)
async def unavailable(request,exc):return JSONResponse(status_code=503,content={'detail':str(exc)})

def site_host(value:str)->str:
    """The host a URL belongs to, without scheme, credentials or default port."""
    netloc=urlsplit(value).netloc or value
    host=netloc.rsplit('@',1)[-1].strip().lower()
    return re.sub(r':(?:80|443)$','',host)

@app.middleware('http')
async def local_writes(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in {'GET','HEAD','OPTIONS'} and origin:
        # Compare hosts, not whole URLs. A platform proxy terminates TLS and forwards
        # over plain HTTP, so the browser says https and the app sees http; that scheme
        # mismatch is the proxy's doing, not a cross-site write.
        forwarded=(request.headers.get('x-forwarded-host') or '').split(',')[0]
        expected=forwarded or request.headers.get('host') or str(request.base_url)
        if site_host(origin)!=site_host(expected):
            return JSONResponse(status_code=403,content={'detail':'Cross-origin writes are disabled.'})
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if request.url.path.startswith('/assets/'):
        # Cheap to revalidate against the ETag; never silently run yesterday's build.
        response.headers['Cache-Control']='no-cache'
    return response

class Turn(BaseModel):
    model_config=ConfigDict(extra='ignore')
    question:str=Field(default='',max_length=600)
    summary:str=Field(default='',max_length=600)
class Ask(BaseModel):
    question:str=Field(min_length=1,max_length=3000)
    history:list[Turn]=Field(default=[],max_length=8)
    session_id:str=Field(default='',max_length=64)
class Draft(BaseModel):prompt:str=Field(min_length=1,max_length=6000)
class IntakeStart(BaseModel):mode:Literal['custom','demo']='custom'
class IntakeSave(BaseModel):
    fields:dict[str,str]={}
    items:list[dict]|None=None
    confirm:bool=False
    expected_version:int|None=None
class WorkflowRequest(BaseModel):
    action:Literal['start','resume','retry']
    approved:bool=False
    actor:str=Field(default='Priya Menon',min_length=1,max_length=100)
    use_ai:bool=True
class Resolve(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    action:Literal['accept','correct','conversion','remap','not_quoted','exclude','freight','qualify']
    actor:str=Field(min_length=1,max_length=100)
    reason:str=Field(min_length=1,max_length=3000)
    expected_version:int
    changes:dict={}
    target_line:int|None=None
    clarification_id:str|None=None
class Clarification(BaseModel):
    action:Literal['draft','send','reply']
    actor:str=Field(default='Priya Menon',min_length=1,max_length=100)
    text:str=Field(default='',max_length=10000)
    clarification_id:str|None=None

def asset_version():
    """A build stamp from the files themselves, so a changed asset is never served stale."""
    stamp=''.join(f'{f.name}:{f.stat().st_mtime_ns}:{f.stat().st_size};'
                  for f in sorted((ROOT/'frontend').iterdir()) if f.is_file())
    return hashlib.sha256(stamp.encode()).hexdigest()[:12]

@app.get('/')
def home():
    page=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
    page=re.sub(r'(/assets/[A-Za-z0-9_.-]+\.(?:js|css))(?=["\'])',rf'\1?v={asset_version()}',page)
    return HTMLResponse(page,headers={'Cache-Control':'no-store'})
@app.get('/health')
def health():return {'status':'ok','ai_configured':has_ai(),'model':MODEL,'version':'1.0.0'}
@app.get('/api/state')
def state():return repo.read()
@app.get('/api/event')
def event():
    d=repo.read();r=d['rfx']
    return {**{k:r[k] for k in ['event_id','title','category','buyer','expected_annual_spend_inr']},'dataset_version':d['dataset_version'],'stage':d['stage'],'rfx_status':d['rfx_status'],'line_count':len(r['items']),'vendor_count':len(d['vendors']),'exception_count':sum(e['status']!='resolved_by_buyer' for e in d['exceptions'])}
@app.get('/api/rfx')
def rfx():return repo.read()['rfx']
@app.get('/api/intake')
def intake_state():return intake.view()
@app.post('/api/intake/new')
def intake_new():
    if jobs.ACTIVE:raise ValueError('Wait for the current extraction to finish')
    def mutate(d):
        evidence=d['evidence'];fresh=repo.initial()
        fresh['intake']=intake.empty()
        version=d['dataset_version'];d.clear();d.update(fresh,dataset_version=version,evidence=evidence)
    repo.change('new_request_previous_version_preserved','buyer',mutate)
    return intake.view()
@app.post('/api/intake/start')
def intake_start(req:IntakeStart):return intake.start(req.mode)
@app.post('/api/intake/chat')
def intake_chat(req:Draft):return intake.chat(req.prompt)
@app.post('/api/intake/attach')
def intake_attach(prompt:str=Form(''),files:list[UploadFile]=File(default=[])):
    if not files:raise ValueError('Attach at least one requirement file')
    if len(prompt)>6000 or len(files)>5:raise ValueError('Use at most 6,000 characters and five attachments')
    folder=repo.runtime_dir()/'uploads'/'intake'/str(uuid4());folder.mkdir(parents=True)
    docs=[];total=0
    for file in files:
        name=Path(file.filename or 'requirement').name;suffix=Path(name).suffix.lower()
        if suffix not in intake_docs.SUPPORTED:raise ValueError('Attach an Excel, CSV, PDF, Word, text or email file')
        content=file.file.read(12*1024*1024+1);total+=len(content)
        if len(content)>12*1024*1024 or total>24*1024*1024:raise ValueError('Use files below 12 MB and packets below 24 MB')
        path=folder/(str(uuid4())+suffix);path.write_bytes(content)
        docs.append({'path':str(path),'filename':name})
    return intake.attach(prompt.strip(),docs)
@app.get('/api/intake/documents/{index}')
def intake_document(index:int):
    doc=intake.document(index)
    return FileResponse(doc['path'],filename=doc['filename'],content_disposition_type='inline')
@app.post('/api/intake/save')
def intake_save(req:IntakeSave):return intake.save(**req.model_dump())
@app.post('/api/intake/share')
def intake_share():return intake.share()
class GraphQuery(BaseModel):
    suppliers:list[str]=[]
    dimensions:list[str]=[]
    requirements:list[int]=[]
    breakdown:Literal['supplier','requirement']='supplier'
@app.get('/api/graph')
def knowledge_graph(version:int|None=None):return knowledge.build(repo.read(version)).as_dict()
@app.get('/api/graph/schema')
def knowledge_schema(version:int|None=None):return knowledge.schema(knowledge.build(repo.read(version)))
@app.get('/api/graph/nodes/{node_id}')
def knowledge_node(node_id:str,version:int|None=None):
    g=knowledge.build(repo.read(version))
    node=g.nodes.get(node_id)
    if not node:raise KeyError('Node not found')
    return {**node,'edges':[e for e in g.edges if node_id in (e['source'],e['target'])]}
@app.post('/api/graph/query')
def knowledge_query(req:GraphQuery):
    spec=req.model_dump()
    if spec.pop('breakdown')=='requirement':
        result=knowledge.by_line(spec)
        return {**result,'verdict':knowledge.line_verdict(result)}
    result=knowledge.compare(spec)
    return {**result,'verdict':knowledge.verdict(result)}
@app.get('/api/knowledge')
def knowledge_base():
    files=dossier.build()
    return {'dataset_version':repo.read()['dataset_version'],'index':files['index.md'],
            'documents':[{'name':name,'characters':len(body)} for name,body in files.items()]}
@app.get('/api/knowledge/{name}')
def knowledge_document(name:str):
    files=dossier.build()
    if name not in files:raise KeyError('No such document')
    return Response(files[name],media_type='text/markdown; charset=utf-8')
@app.post('/api/knowledge/write')
def knowledge_write():
    folder=dossier.write()
    return {'folder':str(folder),'documents':sorted(p.name for p in folder.glob('*.md'))}
@app.get('/api/sessions')
def session_list():return repo.sessions()
@app.get('/api/sessions/{session_id}')
def session_log(session_id:str):return {'id':session_id,'turns':repo.session(session_id)}
@app.get('/api/overview')
def comparison_overview():return insights.overview()
def _amount(value):
    """Crores for big money, lakh for medium, rupees when the difference is small."""
    if value>=1e7:return f'₹{value/1e7:,.3f} Cr'
    if value>=1e5:return f'₹{value/1e5:,.2f} lakh'
    return f'₹{value:,.0f}'

def _award_spec(entry):
    shares={s['supplier_id'].split(':',1)[-1]:s['share'] for s in entry.get('supplier_line_shares') or []}
    return {'supplier_line_shares':shares,
            'qualified_suppliers_only':entry.get('qualified_suppliers_only',True),
            'max_supplier_spend_share':entry.get('max_supplier_spend_share'),
            'max_delivery_days':entry.get('max_delivery_days'),
            'allocation_granularity':('quantity' if shares else entry.get('allocation_granularity') or 'line_item'),
            'equal_split':bool(entry.get('equal_split')),
            'required_supplier_ids':[s.split(':',1)[-1] for s in entry.get('required_supplier_ids') or []],
            'excluded_supplier_ids':[s.split(':',1)[-1] for s in entry.get('excluded_supplier_ids') or []]}

def award_allocation(request,question):
    """Which line goes to which supplier under this award, and what each one wins."""
    entry=(request.get('scenarios') or [{}])[0]
    label=(entry.get('label') or 'Award')[:60]
    result=run_scenario(_award_spec(entry),f'{question} \u2014 {label}','allocation')
    if result['status']!='ok':
        return {'kind':'text','title':'No feasible award','text':(result.get('reason') or 'These constraints cannot be met.')[:200]}
    data=repo.read()
    awarded={a['line_no']:a for a in result['allocation']}
    divided=any(a.get('line_share',1)<0.999 for a in result['allocation'])
    suppliers=[{'id':m['vendor_id'],'name':m['vendor_name'],
                'qualification':data['vendors'].get(m['vendor_id'],{}).get('quality')} for m in result['vendor_mix']]
    blank={'value':None,'display':'\u2014','numeric':None,'evidence_id':None,'source':None,'detail':None}
    rows=[]
    for item in data['rfx']['items']:
        parts={a['vendor_id']:a for a in result['allocation'] if a['line_no']==item['line_no']}
        cells={}
        for s in suppliers:
            won=parts.get(s['id'])
            if not won:
                cells[s['id']]=dict(blank);continue
            detail=f"{won['qty']:,.0f} \u00d7 \u20b9{won['landed_unit_cost']:,.2f}"
            if won.get('line_share',1)<0.999:detail=f"{won['line_share']*100:.0f}% \u00b7 "+detail
            cells[s['id']]={'value':won['total_cost'],'display':f"\u20b9{won['total_cost']:,.0f}",
                            'numeric':won['total_cost'],'evidence_id':won.get('evidence_id'),
                            'source':None,'detail':detail}
        rows.append({'key':f"line:{item['line_no']}",'kind':'number','better':None,'unit':'INR',
                     'label':f"{item['sku']} \u00b7 {item['description']}"[:110],
                     'note':f"{item.get('annual_quantity') or 0:,.0f} {item.get('unit') or 'units'}",
                     'cells':cells,'winners':list(parts) if len(parts)==1 else []})
    portion=lambda m:(f"{m['share']*100:.0f}% of spend" if divided
                      else f"{m['lines']} line{'' if m['lines']==1 else 's'}")
    share=' \u00b7 '.join(f"{m['vendor_name']}: {portion(m)}, \u20b9{m['spend']/1e5:,.1f} lakh"
                      for m in result['vendor_mix'])
    uncovered=result.get('uncovered_lines') or []
    text=f"{share}. Total \u20b9{result['award_total_inr']/1e7:.3f} Cr."
    if uncovered:text+=f" Lines {', '.join(str(x) for x in uncovered)} uncovered."
    return {'kind':'matrix','axis':'allocation','metric':'cost','suppliers':suppliers,'rows':rows,
            'title':request.get('headline') or f'{label}: line allocation','text':text,'segments':{},
            'compared_lines':sorted(awarded),'total_lines':len(data['rfx']['items']),
            'dataset_version':result['dataset_version']}

def compare_awards(request,question,allocations=True):
    """Run each named strategy through the same optimizer and put the totals together."""
    runs=[]
    for entry in request['scenarios'][:4]:
        label=(entry.get('label') or 'Scenario')[:60]
        try:
            result=run_scenario(_award_spec(entry),f"{question} — {label}",'scenario_comparison')
        except Exception as error:
            runs.append({'label':label,'status':'unavailable','reason':str(error)[:160]});continue
        run={'label':label,'status':result['status'],'award_total_inr':result.get('award_total_inr'),
             'reason':result.get('reason'),'complete':result.get('complete_award'),
             'uncovered':result.get('uncovered_lines') or [],'scenario_id':result['id'],
             'supplier_mix':[{'name':m['vendor_name'],'share':m['share'],'lines':m['lines'],'spend':m['spend']}
                             for m in result.get('vendor_mix',[])]}
        if allocations and result['status']=='ok':  # always, so every strategy shows its lines
            run['allocation']=[{'line_no':a['line_no'],'sku':a['sku'],'supplier':a['vendor_name'],
                                'share':a.get('line_share',1),'units':a['qty'],
                                'unit_cost':a['landed_unit_cost'],'cost':a['total_cost']}
                               for a in result['allocation']]
        runs.append(run)
    priced=[r for r in runs if r.get('award_total_inr') is not None]
    best=min(priced,key=lambda r:r['award_total_inr']) if priced else None
    if not priced:
        text='None of these strategies produced a feasible award.'
    elif len(priced)==1:
        text=f"Only “{priced[0]['label']}” is feasible, at {_amount(priced[0]['award_total_inr'])}."
    else:
        worst=max(priced,key=lambda r:r['award_total_inr'])
        gap=worst['award_total_inr']-best['award_total_inr']
        if gap<1000:
            text=(f"Near-identical: “{best['label']}” {_amount(best['award_total_inr'])} vs "
                  f"“{worst['label']}” {_amount(worst['award_total_inr'])} — {_amount(gap)} apart.")
        else:
            text=(f"“{best['label']}” costs {_amount(best['award_total_inr'])} — {_amount(gap)} less than "
                  f"“{worst['label']}” at {_amount(worst['award_total_inr'])}.")
    return {'kind':'scenarios','title':request.get('headline') or 'Award strategies compared','text':text,
            'runs':runs,'best':best['label'] if best else None,'dataset_version':repo.read()['dataset_version']}

def _remember(req,answer):
    if not req.session_id:return answer
    summary=answer.get('text') or answer.get('title') or ''
    if answer.get('kind')=='scenarios':
        summary=' ; '.join(f"{r['label']}: {r.get('award_total_inr')}" for r in answer.get('runs',[]))+' — '+summary
    elif answer.get('kind')=='award':
        scenario=answer.get('scenario') or {}
        summary=f"Award {scenario.get('award_total_inr')} to "+', '.join(m['vendor_name'] for m in scenario.get('vendor_mix',[]))
    repo.log_turn(req.session_id,{'question':req.question,'kind':answer.get('kind'),
                                  'title':answer.get('title'),'summary':str(summary)[:400]})
    return answer

@app.post('/api/analysis')
def analysis(req:Ask):
    # The conversation lives on the server, so a reload does not lose it.
    remembered=[{'question':t['question'],'summary':t.get('summary') or t.get('title') or ''}
                for t in repo.session(req.session_id)[-6:]] if req.session_id else []
    visual=insights.chart(req.question,remembered or [t.model_dump() for t in req.history])
    if visual and visual.get('kind')=='allocation_request':
        if len(visual.get('scenarios') or [])>1:return _remember(req,compare_awards(visual,req.question,allocations=True))
        return _remember(req,award_allocation(visual,req.question))
    if visual and visual.get('kind')=='scenario_request':
        entries=visual['scenarios']
        if len(entries)>1:return _remember(req,compare_awards(visual,req.question))
        if entries[0].get('equal_split') or entries[0].get('allocation_granularity')=='quantity':
            return _remember(req,award_allocation(visual,req.question))
        # A single strategy still runs the router's own spec, not a second interpretation.
        result=run_scenario(_award_spec(entries[0]),req.question,'router_scenario')
        return _remember(req,{'kind':'award','scenario':result,'chart':'pie' if 'pie' in req.question.lower() else 'bar'})
    if visual:return _remember(req,visual)
    result=ask(req)
    return _remember(req,{'kind':'award','scenario':result,'chart':'pie' if 'pie' in req.question.lower() else 'bar'})
@app.post('/api/rfx/draft')
def draft(req:Draft):
    d=repo.read();r=d['rfx']
    if d['rfx_status']=='approved':raise ValueError('This released RFx is frozen for the sourcing event.')
    baseline={'scope':r['scope'],'line_count':len(r['items']),'questionnaire':[{'question':q['question'],'answer_type':q['type'],'mandatory':q['mandatory'],'qualification_rule':str(q.get('maximum',q.get('minimum',''))) or None} for q in r['questionnaire']], 'commercial_terms':{'comparison_basis':'landed cost excluding GST','base_currency':'INR','tax_treatment':'GST excluded','freight_requirement':'State freight explicitly','quote_validity_days':60}}
    result,mode=draft_rfx(req.prompt,baseline)
    # The fixed event retains its 30 specifications and qualification IDs. Copilot
    # proposals are versioned alongside the released contract, never silently remapped.
    repo.change('rfx_drafted','buyer',lambda d:d.update(draft=result,draft_mode=mode,rfx_version=d['rfx_version']+1))
    return {'draft':result,'mode':mode,'note':'30 baseline lines and original qualification rules are retained; proposed questionnaire changes are advisory.'}
@app.get('/api/workflow')
def workflow_status():return graph.status()
@app.post('/api/workflow')
def workflow(req:WorkflowRequest):return graph.run(**req.model_dump())
@app.get('/api/responses')
def responses():
    return [{**{k:v.get(k) for k in ['id','name','format','quality','response_status','method','file','checksum']},'lead_days':v['lead'],'coverage':len(v['facts'])} for v in repo.read()['vendors'].values()]
@app.post('/api/demo/inbox')
def demo_inbox():
    d=repo.read()
    if not repo.demo_offers_match(d['rfx']):raise ValueError('The bundled offers quote the 30 packaging SKUs in the example. Add your own proposals for this request.')
    return {'dataset_version':pipeline.receive_demo()['dataset_version']}
@app.post('/api/process')
def process():return jobs.start()
@app.get('/api/jobs/{jid}')
def job(jid:str):return jobs.read(jid)
@app.post('/api/responses/{vid}/receive')
def receive(vid:str,body:str=Form(''),subject:str=Form('Supplier response'),files:list[UploadFile]=File(default=[])):
    if vid not in repo.read()['vendors']:raise KeyError('Unknown supplier')
    if jobs.ACTIVE:raise ValueError('Wait for the current extraction to finish before changing proposals')
    if repo.read()['rfx_status']!='approved':raise ValueError('Approve the RFx before receiving a response')
    if not body.strip() and not files:raise ValueError('Add an email body or at least one attachment')
    if len(body)>30000 or len(files)>5:raise ValueError('Use at most 30,000 message characters and five attachments')
    docs=[];total=0
    folder=repo.runtime_dir()/'uploads'/str(uuid4());folder.mkdir(parents=True)
    for file in files:
        name=Path(file.filename or 'response').name;suffix=Path(name).suffix.lower()
        if suffix not in {'.xlsx','.docx','.pdf','.eml','.txt','.jpg','.jpeg','.png','.webp'}:raise ValueError('Unsupported attachment format')
        content=file.file.read(12*1024*1024+1);total+=len(content)
        if len(content)>12*1024*1024 or total>24*1024*1024:raise ValueError('Use files below 12 MB and packets below 24 MB')
        path=folder/(str(uuid4())+suffix);path.write_bytes(content)
        docs.append({'path':str(path),'filename':name})
    if body.strip():
        path=folder/'email-body.txt';path.write_text(body)
        docs.insert(0,{'path':str(path),'filename':'email-body.txt','cover_note':bool(files)})
    d=pipeline.receive(vid,docs,body,subject)
    return {'dataset_version':d['dataset_version'],'status':'received'}
@app.post('/api/proposals')
def proposal(supplier_name:str=Form(...),email:str=Form(...),body:str=Form(''),subject:str=Form('Supplier proposal'),files:list[UploadFile]=File(default=[])):
    import re
    if not supplier_name.strip() or len(supplier_name)>160:raise ValueError('Enter a supplier name of at most 160 characters')
    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Enter a valid supplier email address')
    if repo.read()['rfx_status']!='approved':raise ValueError('Approve and share your RFx before adding proposals')
    if jobs.ACTIVE:raise ValueError('Wait for the current extraction to finish before adding proposals')
    if not body.strip() and not files:raise ValueError('Add a message body or attachment')
    if len(body)>30000 or len(files)>5:raise ValueError('Use at most 30,000 characters and five attachments')
    # Validate the entire packet before creating any supplier business record.
    import io as _io
    checked=[];total=0
    for file in files:
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in {'.xlsx','.docx','.pdf','.eml','.txt','.jpg','.jpeg','.png','.webp'}:raise ValueError('Unsupported attachment format')
        content=file.file.read(12*1024*1024+1);total+=len(content)
        if len(content)>12*1024*1024 or total>24*1024*1024:raise ValueError('Use files below 12 MB and packets below 24 MB')
        checked.append(UploadFile(filename=file.filename,file=_io.BytesIO(content)))
    vid='supplier_'+uuid4().hex[:12]
    repo.change('supplier_added','buyer',lambda d:d['vendors'].update({vid:repo.new_vendor(vid,supplier_name.strip(),email.strip())}))
    result=receive(vid,body,subject,checked)
    return {**result,'vendor_id':vid}
@app.get('/api/responses/{vid}/documents/{index}')
def response_document(vid:str,index:int):
    docs=repo.read()['vendors'][vid].get('documents',[])
    if index<0 or index>=len(docs):raise KeyError('Document not found')
    return FileResponse(docs[index]['path'],filename=docs[index]['filename'],content_disposition_type='inline')
@app.post('/api/transcribe')
def transcribe(file:UploadFile=File(...)):
    mime=(file.content_type or '').split(';')[0]
    if mime not in {'audio/webm','audio/mp4','audio/wav','audio/mpeg','audio/ogg','audio/x-m4a'}:raise ValueError('Unsupported audio type')
    data=file.file.read(10*1024*1024+1)
    if len(data)>10*1024*1024:raise ValueError('Record a shorter request (maximum 10 MB)')
    return {'text':transcribe_audio(data,mime),'model':MODEL}
@app.post('/api/responses/{vid}/ingest')
def ingest(vid:str):
    if vid not in repo.VENDORS:raise KeyError('Unknown supplier')
    d=pipeline.ingest(vid)
    return {'dataset_version':d['dataset_version'],'vendor':d['vendors'][vid]}
@app.post('/api/responses/{vid}/upload')
def upload(vid:str,file:UploadFile=File(...)):
    if vid not in repo.VENDORS:raise KeyError('Unknown supplier')
    if repo.read()['rfx_status']!='approved':raise ValueError('Approve RFx before uploading a response')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.xlsx','.docx','.pdf','.eml','.txt','.jpg','.jpeg','.png','.webp'}:raise ValueError('Unsupported response format')
    content=file.file.read(12*1024*1024+1)
    if len(content)>12*1024*1024:raise ValueError('Response exceeds the 12 MB limit')
    path=repo.runtime_dir()/'uploads'/(str(uuid4())+suffix);path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    d=pipeline.receive(vid,[{'path':str(path),'filename':Path(file.filename).name}])
    return {'dataset_version':d['dataset_version'],'vendor':d['vendors'][vid]}
@app.get('/api/comparison')
def comparison():return repo.read()['comparison']
@app.get('/api/exceptions')
def exceptions():return repo.read()['exceptions']
@app.post('/api/exceptions/{eid}/resolve')
def resolve(eid:str,req:Resolve):
    payload=req.model_dump()
    if req.clarification_id:
        c=next((c for c in repo.read()['clarifications'] if c['id']==req.clarification_id and c['exception_id']==eid),None)
        if not c or c['status']!='replied':raise ValueError('A linked supplier reply is required')
        payload['reply']={'id':c['id'],'text':c['reply'],'received_at':c['replied_at']}
    d=pipeline.resolve(eid,payload)
    return {'dataset_version':d['dataset_version']}
@app.post('/api/exceptions/{eid}/clarification')
def clarification(eid:str,req:Clarification):
    d=repo.read();e=next((e for e in d['exceptions'] if e['id']==eid),None)
    if not e:raise KeyError('Exception not found')
    cid=req.clarification_id or str(uuid4())
    proposal=None
    if req.action=='reply' and has_ai():
        proposal=ai_extract_text(req.text,pipeline.context(d['rfx']))
    def mutate(d):
        if req.action=='draft':
            text=req.text or f"Please clarify {e['title']} for {d['rfx']['event_id']}. {e['detail']} Please provide the exact rate, currency, unit/pack size, freight treatment and applicable source evidence."
            d['clarifications'].append({'id':cid,'exception_id':eid,'vendor_id':e['vendor_id'],'text':text,'status':'draft','created_at':repo.now(),'actor':req.actor})
        else:
            c=next((c for c in d['clarifications'] if c['id']==cid and c['exception_id']==eid),None)
            if not c:raise KeyError('Clarification not found')
            if req.action=='send':
                if c['status']!='draft':raise ValueError('Only a draft can be sent')
                c.update(status='sent_simulated',sent_at=repo.now(),approved_by=req.actor)
                if req.text:c['text']=req.text
            else:
                if c['status']!='sent_simulated' or not req.text.strip():raise ValueError('Send the approved draft before capturing a nonempty reply')
                c.update(status='replied',reply=req.text,replied_at=repo.now(),extraction=proposal)
    repo.change('clarification_'+req.action,req.actor,mutate)
    return next(c for c in repo.read()['clarifications'] if c['id']==cid)
@app.get('/api/evidence/{eid}')
def evidence(eid:str,version:int|None=None):
    e=repo.read(version)['evidence'].get(eid)
    if not e:raise KeyError('Evidence not found')
    return e
@app.get('/api/evidence/{eid}/source')
def source(eid:str):
    e=repo.read()['evidence'].get(eid)
    if not e or not e.get('source_path'):raise KeyError('Original source unavailable; see buyer or reply evidence')
    return FileResponse(e['source_path'],filename=e.get('file'),content_disposition_type='inline')
@app.get('/demo-files/{filename}')
def fixture(filename:str):
    allowed={x[1] for x in repo.VENDORS.values()}|{'buyer_rfx_reference.xlsx','manifest.json'}
    if filename not in allowed:raise KeyError('Fixture not found')
    return FileResponse(DATA_DIR/filename,content_disposition_type='inline')
@app.get('/api/extraction/{vid}')
def extraction(vid:str):
    v=repo.read()['vendors'].get(vid)
    if not v:raise KeyError('Unknown supplier')
    return v

def run_scenario(spec,question='',interpreter='structured_form'):
    d=repo.read()
    if d['rfx_status']!='approved' or not d['comparison']:raise ValueError('Approve RFx and ingest responses before analysis')
    result=solve_scenario(spec,d)
    result['dataset_version']=d['dataset_version']
    result['open_exceptions']=[{'id':e['id'],'title':e['title']} for e in d['exceptions'] if e['status']!='resolved_by_buyer']
    result['provisional']=bool(result['open_exceptions'])
    if result.get('solver_status')=='limit_or_error':result['status']='solver_limit'
    return repo.save_scenario(result,question,interpreter)
@app.post('/api/scenario')
def scenario(req:ValidatedSpec):return run_scenario(req.model_dump())
@app.post('/api/ask')
def ask(req:Ask):
    spec,mode=interpret_scenario(req.question,list(repo.read()['vendors']))
    return run_scenario(spec,req.question,mode)
@app.get('/api/scenarios')
def scenarios():return repo.scenarios()
@app.get('/api/scenarios/{sid}')
def saved(sid:str):return repo.scenario(sid)
@app.post('/api/scenarios/{sid}/recompute')
def recompute(sid:str):
    s=repo.scenario(sid)
    return run_scenario(s['spec'],s['question'],'recomputed_exact_constraints')
@app.get('/api/scenarios/{sid}/export')
def export(sid:str):
    s=repo.scenario(sid);out=io.StringIO()
    writer=csv.writer(out);writer.writerow(['scenario_id','dataset_version','stale','line','sku','supplier','quantity','landed_inr','extended_inr','evidence_id'])
    for a in s.get('allocation',[]):writer.writerow([sid,s['dataset_version'],s['stale'],a['line_no'],a['sku'],a['vendor_name'],a['qty'],a['landed_unit_cost'],a['total_cost'],a['evidence_id']])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="award-{sid}.csv"'})
@app.get('/api/audit')
def audit():return repo.audit()
@app.get('/api/datasets/{version}')
def version(version:int):return repo.read(version)
