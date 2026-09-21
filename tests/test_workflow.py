import copy
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import repository as repo, pipeline, graph
from backend.app.main import app
from backend.app.scenario import solve_scenario, ValidatedSpec
from backend.app.store import DATA_DIR

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('AERCHAIN_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('GOOGLE_API_KEY',raising=False)
    return TestClient(app)

def approve(client):
    # The 30-line packaging event is opt-in now; a first open starts on an empty request.
    assert client.post('/api/intake/start',json={'mode':'demo'}).status_code==200
    assert client.post('/api/workflow',json={'action':'start','use_ai':False}).status_code==200
    r=client.post('/api/workflow',json={'action':'resume','approved':True,'actor':'Test buyer'})
    assert r.status_code==200,r.text
    pipeline.receive_demo()
    graph.run('process')
    return repo.read()

def resolve(client,eid,action='accept',**extra):
    return client.post('/api/exceptions/'+eid+'/resolve',json={'action':action,'actor':'Test buyer','reason':'Verified against source for regression test','expected_version':repo.read()['dataset_version'],**extra})

def test_approval_gate_and_durable_interrupt(client):
    assert client.post('/api/intake/start',json={'mode':'demo'}).status_code==200
    assert client.post('/api/responses/packright/ingest').status_code==422
    r=client.post('/api/workflow',json={'action':'start','use_ai':False}).json()
    assert r['interrupts'][0]['type']=='rfx_approval'
    status=graph.status()
    assert status['id']==r['id'] and status['next']==['approval']
    client.post('/api/workflow',json={'action':'resume','approved':False})
    assert repo.read()['rfx_status']=='draft'
    r=client.post('/api/workflow',json={'action':'resume','approved':True})
    assert r.status_code==200,r.text
    assert r.json()['interrupts'][0]['type']=='response_collection'
    pipeline.receive_demo();graph.run('process')
    assert graph.status()['interrupts'][0]['type']=='exception_review'

def test_native_extraction_against_csv(client):
    d=approve(client)
    assert {v:len(d['vendors'][v]['facts']) for v in ['packright','corrpro','boxworks','greencarton']}=={'packright':30,'corrpro':30,'boxworks':27,'greencarton':30}
    assert [d['vendors'][v]['quality'] for v in ['packright','corrpro','boxworks','greencarton']]==['pass','pass','pending','pass']
    prior=[e for e in d['exceptions'] if e['vendor_id']=='greencarton' and e['type']=='review_price']
    assert len(prior)==4
    for e in prior:
        assert d['comparison'][e['line_no']-1]['vendors']['greencarton']['landed_unit_cost'] is None
        r=resolve(client,e['id']);assert r.status_code==200,r.text
    d=repo.read();checked=0
    with (DATA_DIR/'normalized_truth.csv').open() as f:
        for row in csv.DictReader(f):
            if row['vendor']=='alphapack' or row['status']!='quoted':continue
            q=d['comparison'][int(row['line_no'])-1]['vendors'][row['vendor']]
            assert q['evidence_id'] in d['evidence']
            assert abs(q['landed_unit_cost']-float(row['landed_unit_cost_inr']))<=.020001
            checked+=1
    assert checked==117
    assert d['comparison'][6]['vendors']['boxworks']['landed_unit_cost'] is None

def test_correction_history_stale_and_restart(client):
    d=approve(client)
    s=client.post('/api/scenario',json={}).json()
    assert s['status']=='ok'
    eid='greencarton:6:review_price'
    original=d['comparison'][5]['vendors']['greencarton']['evidence_id']
    r=resolve(client,eid,'correct',changes={'raw_price':20,'raw_basis':'piece','raw_currency':'INR'})
    assert r.status_code==200,r.text
    updated=repo.read();q=updated['comparison'][5]['vendors']['greencarton']
    assert q['landed_unit_cost']==20.4
    assert updated['evidence'][q['evidence_id']]['buyer_override']['parent_evidence_id']==original
    assert repo.read(d['dataset_version'])['comparison'][5]['vendors']['greencarton']['landed_unit_cost'] is None
    assert repo.scenario(s['id'])['stale']
    old=solve_scenario(s['spec'],repo.read(s['dataset_version']))
    assert old['award_total_inr']==s['award_total_inr']
    out=subprocess.check_output([sys.executable,'-c','from backend.app.repository import read; print(read()["dataset_version"])'],env=os.environ).decode().strip()
    assert int(out)==updated['dataset_version']
    current=client.post('/api/scenarios/'+s['id']+'/recompute',json={}).json()
    assert current['id']!=s['id'] and not current['stale']
    assert client.get('/api/evidence/'+original).status_code==200

@pytest.mark.parametrize('share',[.45,.55])
def test_cap_and_objective(client,share):
    d=approve(client);base=solve_scenario({},d);s=solve_scenario({'max_supplier_spend_share':share},d)
    assert s['status']=='ok' and len(s['allocation'])==30
    assert s['award_total_inr']>=base['award_total_inr']
    assert max(x['spend']/s['award_total_inr'] for x in s['vendor_mix'])<=share+1e-8
    assert all(d['vendors'][a['vendor_id']]['quality']=='pass' for a in s['allocation'])

def test_independent_cheapest_oracle(client):
    d=approve(client);s=solve_scenario({},d)
    oracle=sum(min(q['landed_unit_cost'] for q in r['vendors'].values() if q['qualification']=='pass' and q['landed_unit_cost'] is not None and not q.get('blocking_exception'))*r['qty'] for r in d['comparison'])
    assert abs(oracle-s['award_total_inr'])<.01

@pytest.mark.parametrize('spec',[{'max_delivery_days':1},{'max_supplier_spend_share':.2},{'required_supplier_ids':['alphapack']},{'excluded_supplier_ids':list(repo.VENDORS)}])
def test_infeasible_without_relaxing(client,spec):
    d=approve(client);s=solve_scenario(spec,d)
    assert s['status']=='infeasible'
    assert all(s['spec'][k]==v for k,v in spec.items())

def test_required_not_exclusive(client):
    d=approve(client);s=solve_scenario({'required_supplier_ids':['greencarton']},d)
    assert s['status']=='ok' and 'greencarton' in [a['vendor_id'] for a in s['allocation']]
    assert s['supplier_count']>1

@pytest.mark.parametrize('spec',[{'max_supplier_spend_share':0},{'max_supplier_spend_share':1.5},{'max_delivery_days':-1},{'objective':'invent'},{'excluded_supplier_ids':['unknown']}])
def test_invalid_spec(client,spec):
    approve(client)
    assert client.post('/api/scenario',json=spec).status_code==422

def test_unknown_freight_currency_pack_and_evidence(client):
    d=approve(client);v=d['vendors']['packright'];f=copy.deepcopy(v['facts'][0]);i=d['rfx']['items'][0]
    assert pipeline.normalized(f,{},i,d['rfx'])['landed_unit_cost'] is None
    for changes in [{'raw_currency':'EUR'},{'raw_basis':'bundle','pack_size':0},{'raw_price':None},{'evidence_id':None},{'confidence':.5}]:
        n=pipeline.normalized({**f,**changes},v['terms'],i,d['rfx'])
        assert n['blocking_exception'] and n['landed_unit_cost'] is None

def test_clarification_requires_approval_and_buyer_application(client):
    approve(client);eid='boxworks:7:missing_quote'
    c=client.post('/api/exceptions/'+eid+'/clarification',json={'action':'draft'}).json()
    assert c['status']=='draft'
    body={'action':'reply','clarification_id':c['id'],'text':'L7 BX-5P-480-330-260: INR 24 per piece, freight INR 0.32 per piece.'}
    assert client.post('/api/exceptions/'+eid+'/clarification',json=body).status_code==422
    assert client.post('/api/exceptions/'+eid+'/clarification',json={'action':'send','clarification_id':c['id']}).status_code==200
    assert client.post('/api/exceptions/'+eid+'/clarification',json=body).status_code==200
    assert repo.read()['comparison'][6]['vendors']['boxworks']['landed_unit_cost'] is None
    r=resolve(client,eid,'correct',changes={'raw_price':24,'raw_basis':'piece','raw_currency':'INR'},clarification_id=c['id'])
    assert r.status_code==200,r.text
    d=repo.read();q=d['comparison'][6]['vendors']['boxworks'];assert q['landed_unit_cost']==24.32
    assert d['evidence'][q['evidence_id']]['clarification_reply']['id']==c['id']

def test_optimistic_lock_and_duplicate_ingestion(client):
    d=approve(client);version=d['dataset_version']
    resolve(client,'greencarton:6:review_price')
    assert client.post('/api/exceptions/greencarton:13:review_price/resolve',json={'action':'accept','actor':'Buyer','reason':'Confirmed','expected_version':version}).status_code==422
    current=repo.read()['dataset_version'];pipeline.ingest('greencarton',False)
    assert repo.read()['dataset_version']==current

def test_unreadable_cannot_be_accepted(client):
    approve(client)
    assert resolve(client,'alphapack:18:extraction_required').status_code==422

def test_source_paths_and_truth_not_public(client):
    approve(client)
    assert client.get('/demo-files/normalized_truth.csv').status_code==404
    assert client.get('/demo-files/demo_state.json').status_code==404
    eid=repo.read()['vendors']['packright']['facts'][0]['evidence_id']
    assert client.get('/api/evidence/'+eid+'/source').status_code==200
    assert client.post('/api/workflow',json={'action':'resume'},headers={'Origin':'https://malicious.example'}).status_code==403

# A TLS-terminating proxy (Railway, Render, Fly) forwards to the container over plain
# HTTP. Comparing whole URLs made the browser's https origin look cross-site, so every
# write — including attaching a requirement sheet — came back 403.
PROXIED = {'origin': 'https://source-pilot.up.railway.app', 'host': 'source-pilot.up.railway.app'}

def test_writes_survive_a_tls_terminating_proxy(client):
    assert client.post('/api/intake/start', json={'mode': 'demo'}, headers=PROXIED).status_code == 200

def test_writes_survive_a_forwarded_host(client):
    headers = {'origin': 'https://source-pilot.up.railway.app', 'host': 'container.internal:8080',
               'x-forwarded-host': 'source-pilot.up.railway.app'}
    assert client.post('/api/intake/start', json={'mode': 'demo'}, headers=headers).status_code == 200

def test_a_genuine_cross_site_write_is_still_refused(client):
    headers = {'origin': 'https://evil.example.com', 'host': 'source-pilot.up.railway.app'}
    r = client.post('/api/intake/start', json={'mode': 'demo'}, headers=headers)
    assert r.status_code == 403 and 'Cross-origin' in r.json()['detail']

def test_a_requirement_sheet_uploads_through_the_proxy(client):
    import io, openpyxl
    client.post('/api/intake/start', json={'mode': 'custom'}, headers=PROXIED)
    book = openpyxl.Workbook(); sheet = book.active
    sheet.append(['SKU', 'Description', 'Annual quantity', 'Unit'])
    sheet.append(['RSC-001', 'Regular slotted carton 400x300x200', 12000, 'piece'])
    sheet.append(['RSC-002', 'Regular slotted carton 600x400x300', 8000, 'piece'])
    buffer = io.BytesIO(); book.save(buffer)
    r = client.post('/api/intake/attach', data={'prompt': 'Here are the lines we need.'},
                    files={'files': ('requirement.xlsx', buffer.getvalue(),
                                     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
                    headers=PROXIED)
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 2
