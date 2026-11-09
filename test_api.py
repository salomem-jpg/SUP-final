import importlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMPDIR=TemporaryDirectory()
os.environ['DATABASE_PATH']=str(Path(TEMPDIR.name)/'test.sqlite3')
os.environ['REQUIRE_AUTH']='0'
server=importlib.import_module('server')


def test_homepage_and_health():
    with TestClient(server.app) as client:
        r=client.get('/')
        assert r.status_code==200 and 'Supplier Capability Hub' in r.text
        assert '/api/bootstrap' in r.text
        assert client.get('/healthz').json()['status']=='ok'


def test_bootstrap_catalog_and_synthetic_only():
    with TestClient(server.app) as client:
        data=client.get('/api/bootstrap').json()
        assert len(data['state']['cases'])==4
        assert data['integrations']['snowflake']=='mock-data'
        assert len(data['evaluations']['DEMO-EX-001']['recommendations'])==21
        catalog=client.get('/api/catalog').json()
        assert len(catalog['criteria'])==16
        assert len(catalog['interventions'])==21
        assert not catalog['copilot_connected'] and not catalog['snowflake_connected']
        assert data['evaluations']['DEMO-EX-001']['coverage']['total']==16


def test_business_case_formula():
    data=server.initial()['cases'][0]
    calc=server.evaluate(data)
    assert calc['net']==pytest.approx(5_200_000,abs=2)
    assert calc['p']==pytest.approx(.6,abs=1e-6)
    assert not calc['gates']['supplier_willingness']  # with conditions is not a pass


def test_state_save_reload_and_no_client_supplied_immutable_data():
    with TestClient(server.app) as client:
        state=client.get('/api/bootstrap').json()['state']
        case=state['cases'][0]
        case['name']='HACKED SUPPLIER NAME'
        case['ratings']['A2']=1.0
        case['reviewDecision']='Approved'
        result=client.post('/api/state',json=state)
        assert result.status_code==200, result.text
        assert result.json()['state']['cases'][0]['name']=='Atlas Precision Components'
        assert result.json()['state']['cases'][0]['reviewDecision']=='Pending'
        fresh=client.get('/api/bootstrap').json()['state']
        assert fresh['cases'][0]['ratings']['A2']==1
        assert fresh['cases'][0]['name']!='HACKED SUPPLIER NAME'
        assert client.patch('/api/suppliers/DEMO-EX-001/assessment',json={'ratings':{'A2':2}}).status_code==200
        assert client.get('/api/suppliers/DEMO-EX-001').json()['supplier']['ratings']['A2']==2


def test_server_approval_gates_and_invalidation():
    with TestClient(server.app) as client:
        sid='DEMO-EX-001'
        body={'decision':'Approved','note':'Reviewed by demo manager'}
        # With-conditions supplier willingness must not count as gate pass.
        r=client.post(f'/api/suppliers/{sid}/decision',json=body)
        assert r.status_code==422
        patch=client.patch(f'/api/suppliers/{sid}/business-case',json={'finance':{'supplier_willing':'Yes'}})
        assert patch.status_code==200
        ok=client.post(f'/api/suppliers/{sid}/decision',json=body)
        assert ok.status_code==200,ok.text
        assert ok.json()['supplier']['reviewDecision']=='Approved'
        edited=client.patch(f'/api/suppliers/{sid}/business-case',json={'finance':{'cost_tooling':8_000_000}})
        assert edited.status_code==200
        assert edited.json()['supplier']['reviewDecision']=='Pending'
        assert not edited.json()['evaluation']['gates']['siemens_economics']
        assert client.post(f'/api/suppliers/{sid}/decision',json=body).status_code==422


def test_synthetic_assistant_and_compare():
    with TestClient(server.app) as client:
        cases=client.get('/api/bootstrap').json()['state']['cases']
        ids=[x['id'] for x in cases]
        compared=client.get('/api/compare',params={'ids':','.join(ids[:3])})
        assert compared.status_code==200
        assert len(compared.json()['suppliers'])==3
        assert client.get('/api/compare',params={'ids':','.join(ids)}).status_code==422
        ans=client.post('/api/assistant',json={'supplier_id':ids[0],'message':'What is our business case?'}).json()
        assert ans['kind']=='deterministic-preview' and '€' in ans['answer']
        assert not ans['copilot_connected']


def test_different_sessions_are_isolated():
    with TestClient(server.app) as a,TestClient(server.app) as b:
        a.get('/api/bootstrap')
        b.get('/api/bootstrap')
        a.patch('/api/suppliers/DEMO-EX-001/assessment',json={'ratings':{'A2':1}})
        assert b.get('/api/suppliers/DEMO-EX-001').json()['supplier']['ratings']['A2']!=1


def test_export_reset_and_questionnaire():
    with TestClient(server.app) as client:
        client.get('/api/bootstrap')
        sid='DEMO-NEW-002'
        client.patch(f'/api/suppliers/{sid}/questionnaire',json={'questionnaire':{'B1':5}})
        result=client.get('/api/export').json()
        assert result['state']['cases'][1]['questionnaire']['B1']==5
        client.post('/api/reset')
        assert 'B1' not in client.get('/api/suppliers/'+sid).json()['supplier']['questionnaire']


def test_json_input_validation_and_cross_origin():
    with TestClient(server.app) as client:
        client.get('/api/bootstrap')
        assert client.post('/api/state',data='broken',headers={'Content-Type':'application/json'}).status_code==400
        assert client.post('/api/state',json={'cases':'bad'}).status_code==200  # ignores invalid cases, preserves original
        assert client.post('/api/state',json={},headers={'Origin':'https://some-other-site.example'}).status_code==403
        assert client.patch('/api/suppliers/bad/assessment',json={'ratings':{'A1':3}}).status_code==404
        assert client.post('/api/assistant',json={'supplier_id':'DEMO-EX-001','message':''}).status_code==422


def test_basic_auth_when_enabled(monkeypatch):
    monkeypatch.setattr(server,'REQUIRE_AUTH',True)
    monkeypatch.setattr(server,'APP_PASSWORD','strong-demo-password')
    with TestClient(server.app) as client:
        assert client.get('/').status_code==401
        assert client.get('/healthz').status_code==200
        assert client.get('/',auth=('demo','wrong')).status_code==401
        assert client.get('/',auth=('demo','strong-demo-password')).status_code==200


def test_backup_restore_resets_approvals_and_returns_state():
    with TestClient(server.app) as client:
        client.get('/api/bootstrap')
        client.patch('/api/suppliers/DEMO-EX-001/assessment', json={'ratings': {'A2': 1.8}})
        backup=client.get('/api/export').json()
        client.post('/api/reset')
        r=client.post('/api/import',json=backup)
        assert r.status_code==200, r.text
        assert r.json()['state']['cases'][0]['ratings']['A2']==1.8
        assert r.json()['state']['cases'][0]['reviewDecision']=='Pending'
        assert client.post('/api/import',json={'state':backup['state']}).status_code==422
