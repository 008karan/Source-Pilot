"""Explicit opt-in live smoke test using fictional buyer/supplier content only."""
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__=='__main__':
    os.environ['GOOGLE_API_KEY']=getpass.getpass('Runtime API secret (hidden): ')
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app import repository as repo, graph
    results=[]
    def check(name,value):
        results.append({'name':name,'passed':bool(value)});print(('PASS: ' if value else 'FAIL: ')+name,flush=True)
    with tempfile.TemporaryDirectory(prefix='aerchain-intake-live-') as tmp:
        os.environ['AERCHAIN_DATA_DIR']=tmp
        with TestClient(app) as c:
            r=c.post('/api/intake/chat',json={'prompt':'We need 120 ergonomic office chairs. Please help me prepare the RFQ.'})
            assert r.status_code==200,r.text
            v=r.json();check('Live category-independent follow-up',bool(v['messages'][-1]['text']) and bool(v['missing']) and len(v['items'])==1)
            r=c.post('/api/intake/chat',json={'prompt':'Category: office furniture. Scope: purchase 120 ergonomic chairs, unit piece. Specifications: adjustable lumbar support, mesh back and 3-year warranty; inspect on delivery. Deliver to Bengaluru office by 20 November 2026. Budget INR 600,000. Price INR per piece, freight included, GST excluded. Payment net 30 days after acceptance. Proposals due 1 October 2026, 17:00 IST. Offers valid 60 days. Compliance: suppliers must confirm compliance with the stated specifications; no additional certifications required. Evaluation: meet specifications, then lowest landed cost and delivery. Owner: Demo Buyer; clarification email buyer@example.com. Supplier preferences: none.'})
            assert r.status_code==200,r.text
            v=r.json();check('All checklist essentials captured',not v['missing'])
            check('Explicit confirmation still required',not v['ready'] and c.post('/api/intake/share',json={}).status_code==422)
            r=c.post('/api/intake/save',json={'fields':{},'confirm':True});assert r.status_code==200,r.text
            r=c.post('/api/intake/share',json={});assert r.status_code==200,r.text
            check('No invented furniture supplier matches',r.json()['suppliers']==[])
            r=c.post('/api/proposals',data={'supplier_name':'Fictional Chair Supplier','email':'quotes@example.com','body':'We quote RFQ item ITEM-001: 120 ergonomic chairs. INR 2500 per piece. Freight included. GST excluded. Delivery lead time 10 days. Q1: Yes, we comply with all buyer specifications including adjustable lumbar support, mesh back and 3-year warranty. Payment net 30 days. Offer valid 60 days.'})
            assert r.status_code==200,r.text
            vid=r.json()['vendor_id'];graph.run('process')
            d=repo.read();v=d['vendors'][vid]
            check('Live email proposal extracted',len(v['facts'])==1 and d['comparison'][0]['vendors'][vid]['landed_unit_cost']==2500)
            check('Source evidence retained',d['comparison'][0]['vendors'][vid]['evidence_id'] in d['evidence'])
            r=c.post('/api/analysis',json={'question':'Show a pie chart of the cheapest qualified award'});assert r.status_code==200,r.text
            check('Live award request returns pie-chart data',r.json()['kind']=='award' and r.json()['chart']=='pie' and r.json()['scenario'].get('award_total_inr')==300000)
            check('No invented savings baseline',r.json()['scenario'].get('savings_inr') is None)
    output=Path('evaluation-intake');output.mkdir(exist_ok=True)
    (output/'live-smoke.json').write_text(json.dumps({'checks':results,'passed':all(x['passed'] for x in results)},indent=2))
    if not all(x['passed'] for x in results):raise SystemExit(1)
