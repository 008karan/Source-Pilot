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


# ── Award selection ──────────────────────────────────────────────────────────
# Every figure on the award screen is arithmetic over the reviewed snapshot, so
# these assert relationships that must hold for ANY event, not fixture numbers.

def award_view(client):
    from backend.app import award
    approve(client)
    return award.view(repo.read())


def test_award_is_not_offered_before_responses_are_processed(client):
    from backend.app import award
    view = award.view(repo.read())
    assert view['ready'] is False and view['scenarios'] == []
    assert 'response processing' in view['message']


def test_the_three_standing_scenarios_are_generated(client):
    view = award_view(client)
    assert [s['key'] for s in view['scenarios']] == ['lowest_cost', 'single_supplier', 'fastest_delivery']
    assert view['event']['line_item_count'] == len(repo.read()['rfx']['items'])


def test_lowest_cost_matches_the_optimizer(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    optimum = solve_scenario({'qualified_suppliers_only': True}, data)
    assert abs(award.lowest_cost(data)['total_value'] - optimum['award_total_inr']) < 1


def test_no_scenario_ever_awards_an_unqualified_supplier(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    for scenario in award.defaults(data):
        for line in scenario['allocation']:
            if line['supplier_id']:
                assert data['vendors'][line['supplier_id']]['quality'] == 'pass', scenario['name']


def test_single_supplier_uses_one_supplier_and_costs_no_less_than_the_optimum(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    single, cheapest = award.single_supplier(data), award.lowest_cost(data)
    if single['status'] == 'ok':
        assert single['supplier_count'] == 1
        assert single['total_value'] >= cheapest['total_value'] - 1
    else:
        assert 'not feasible' in single['reason']


def test_fastest_delivery_is_never_slower_than_the_cheapest_award(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    fastest, cheapest = award.fastest_delivery(data), award.lowest_cost(data)
    if fastest['max_lead_time'] is not None and cheapest['max_lead_time'] is not None:
        assert fastest['max_lead_time'] <= cheapest['max_lead_time']


def test_every_line_appears_exactly_once_in_an_allocation(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    for scenario in award.defaults(data):
        lines = [a['line_item_id'] for a in scenario['allocation']]
        assert sorted(lines) == sorted(r['line_no'] for r in data['comparison'])
        assert len(lines) == len(set(lines))


def test_totals_are_the_sum_of_their_own_lines(client):
    from backend.app import award
    approve(client)
    for scenario in award.defaults(repo.read()):
        expected = sum(a['line_total'] for a in scenario['allocation'] if a['supplier_id'])
        assert abs(scenario['total_value'] - expected) < 1


def test_an_analysis_run_can_be_saved_and_then_appears_on_the_award_screen(client):
    from backend.app import award
    approve(client)
    run = client.post('/api/scenario', json={'qualified_suppliers_only': True}).json()
    saved = client.post('/api/award/scenarios', json={'scenario_id': run['id'], 'name': 'Cheapest qualified'})
    assert saved.status_code == 200, saved.text
    view = client.get('/api/award').json()
    kept = [s for s in view['scenarios'] if s['source'] == 'analysis']
    assert len(kept) == 1 and kept[0]['name'] == 'Cheapest qualified'
    assert abs(kept[0]['total_value'] - run['award_total_inr']) < 1


def test_confirming_an_award_stores_it_against_the_event(client):
    approve(client)
    confirmed = client.post('/api/award/confirm', json={'scenario': 'lowest_cost', 'actor': 'Test buyer'})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body['status'] == 'selected' and body['confirmed_by'] == 'Test buyer'
    assert body['allocated_line_items'] == body['total_line_items']
    assert repo.read()['award']['id'] == body['id']
    assert client.get('/api/award').json()['award']['id'] == body['id']


def test_a_saved_scenario_is_flagged_when_the_data_moves_underneath_it(client):
    from backend.app import award
    approve(client)
    run = client.post('/api/scenario', json={'qualified_suppliers_only': True}).json()
    client.post('/api/award/scenarios', json={'scenario_id': run['id'], 'name': 'Before the change'})
    assert not client.get('/api/award').json()['scenarios'][-1]['stale']

    def bump(d):
        d['comparison'][0]['qty'] = (d['comparison'][0]['qty'] or 0) + 1
    repo.change('price_moved', 'test', bump)

    saved = client.get('/api/award').json()['scenarios'][-1]
    assert saved['stale'] is True
    refused = client.post('/api/award/confirm', json={'scenario': saved['id'], 'actor': 'Test buyer'})
    assert refused.status_code >= 400 and 'recalculation' in refused.text


def test_exclusion_reasons_come_from_the_qualification_engine(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    excluded = {e['supplier_id']: e for e in award.exclusions(data)}
    for vid, vendor in data['vendors'].items():
        if vendor.get('quality') == 'pass':
            continue
        assert vid in excluded and excluded[vid]['reasons']


def test_the_award_screen_never_calls_a_model():
    source = (Path(__file__).resolve().parents[1] / 'backend' / 'app' / 'award.py').read_text()
    assert 'import' in source and ' ai' not in source.replace('award', '')
    assert 'gemini' not in source.lower() and 'from .ai' not in source


def test_a_split_line_is_two_rows_but_still_one_line(client):
    """A quantity split must not inflate the line count or the required quantity."""
    from backend.app import award
    approve(client)
    run = client.post('/api/scenario', json={'qualified_suppliers_only': True,
                                             'max_supplier_spend_share': 0.6,
                                             'allocation_granularity': 'quantity'}).json()
    if run['status'] != 'ok':
        pytest.skip('this fixture has no feasible split')
    data = repo.read()
    scenario = award.from_solver(data, run, 'Split')
    coverage = scenario['coverage']
    assert coverage['total_lines'] == len(data['comparison'])
    assert coverage['allocated_lines'] <= coverage['total_lines']
    assert abs(coverage['required_quantity'] - sum(r['qty'] for r in data['comparison'])) < 1
    assert abs(coverage['allocated_quantity'] - coverage['required_quantity']) < 1
    assert len(scenario['allocation']) >= coverage['total_lines']


def test_a_supplier_level_note_does_not_flag_every_line(client):
    """One advisory about a supplier is said once, not stamped on all their rows."""
    from backend.app import award
    approve(client)
    data = repo.read()
    vendor_level = {e['vendor_id'] for e in data['exceptions']
                    if e['status'] != 'resolved_by_buyer' and not e.get('line_no')}
    scenario = award.lowest_cost(data)
    for line in scenario['allocation']:
        vid = line['supplier_id']
        if vid and vid in vendor_level and data['vendors'][vid]['quality'] == 'pass':
            line_level = {e['line_no'] for e in data['exceptions']
                          if e['vendor_id'] == vid and e['status'] != 'resolved_by_buyer'}
            if line['line_item_id'] not in line_level:
                assert line['eligibility_status'] == 'eligible'
    if vendor_level & {a['supplier_id'] for a in scenario['allocation'] if a['supplier_id']}:
        assert scenario['advisories']


def test_a_saved_scenario_is_named_for_its_constraints_not_the_question(client):
    """The buyer's sentence is kept as a note; the card gets a title from the spec."""
    from backend.app import award
    approve(client)
    question = 'What happens if I cap any single supplier at 60% of the award value?'
    from backend.app.main import run_scenario
    run = run_scenario({'qualified_suppliers_only': True, 'max_supplier_spend_share': 0.6,
                        'allocation_granularity': 'quantity'}, question, 'test')
    saved = client.post('/api/award/scenarios', json={'scenario_id': run['id']}).json()
    assert saved['name'] == 'Max 60% per supplier'
    assert question not in saved['name'] and saved['notes'] == question
    assert len(saved['name']) <= 80


def test_scenario_names_describe_whatever_was_constrained(client):
    from backend.app import award
    approve(client)
    data = repo.read()
    qualified = [v for v, vendor in data['vendors'].items() if vendor['quality'] == 'pass']
    cases = [
        ({'qualified_suppliers_only': True}, 'Cheapest qualified allocation'),
        ({'max_delivery_days': 13}, 'Lead time under 13 days'),
        ({'excluded_supplier_ids': qualified[:1]}, 'Without ' + data['vendors'][qualified[0]]['name']),
        ({'required_supplier_ids': qualified[:1]}, 'Must include ' + data['vendors'][qualified[0]]['name']),
    ]
    for spec, expected in cases:
        assert award.title_for(data, {'spec': spec, 'vendor_mix': []}) == expected


def test_a_named_scenario_keeps_the_name_the_buyer_gave_it(client):
    from backend.app.main import run_scenario
    approve(client)
    run = run_scenario({'qualified_suppliers_only': True}, 'anything', 'test')
    saved = client.post('/api/award/scenarios',
                        json={'scenario_id': run['id'], 'name': 'Board approved option'}).json()
    assert saved['name'] == 'Board approved option'
