import concurrent.futures
import json
import math
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from marketlens.analytics import bars, summary, volume_profile
from marketlens.data import demo, load, read_csv, register, utc
from marketlens.engine import compare, paired_bootstrap, prepare, simulate
from marketlens.models import Config
from marketlens.store import Store


def flat_frame():
    t=pd.date_range('2025-01-09T09:30:00Z',periods=4,freq='min')
    return pd.DataFrame({'timestamp':t,'volume':[100.]*4,'notional':[10000.]*4,
       'first':[100.]*4,'last':[100.]*4,'vwap':[100.]*4,'quote_mid':[100.]*4,'spread_bps':[0.]*4})

def config(**kwargs):
    return Config(dataset_id='0'*16,start='2025-01-09T09:30:00Z',end='2025-01-09T09:34:00Z',
                  training_end='2025-01-09T00:00:00Z',quantity=40,fee_bps=0,impact_bps=0,noise_bps=0,**kwargs)

class NumericalTests(unittest.TestCase):
    def test_flat_tape_zero_cost(self):
        for side in ['buy','sell']:
            c=config(side=side)
            for p in ['TWAP','VWAP','POV']:
                result=simulate(flat_frame(),np.ones(4)/4,c,p,100)['metrics']
                self.assertAlmostEqual(result['implementation_shortfall_bps'],0)
                self.assertAlmostEqual(result['filled_quantity'],40)
    def test_uniform_vwap_equals_twap(self):
        c=config();a=simulate(flat_frame(),np.ones(4)/4,c,'TWAP');b=simulate(flat_frame(),np.ones(4)/4,c,'VWAP')
        self.assertEqual([x['quantity'] for x in a['fills']],[x['quantity'] for x in b['fills']])
    def test_sell_buy_spread_sign_and_fee(self):
        f=flat_frame();f['spread_bps']=10.
        c=config().model_copy(update={'fee_bps':2.})
        for side in ['buy','sell']:
            m=simulate(f,np.ones(4)/4,c.model_copy(update={'side':side}),'TWAP')['metrics']
            self.assertAlmostEqual(m['filled_arrival_slippage_bps'],5,places=7)
            self.assertGreater(m['implementation_shortfall_bps'],6.99)
    def test_capacity_and_no_overfill(self):
        c=config().model_copy(update={'quantity':1000.,'max_participation':.05,'participation':.05})
        r=simulate(flat_frame(),np.ones(4)/4,c,'TWAP')
        self.assertEqual(r['metrics']['filled_quantity'],20)
        self.assertEqual(r['metrics']['unfilled_quantity'],980)
        self.assertTrue(all(x['participation']<=.05+1e-10 for x in r['fills']))
    def test_pov_uses_lagged_volume(self):
        f=flat_frame();f.loc[0,'volume']=1000
        r=simulate(f,np.ones(4)/4,config(),'POV',0)
        self.assertEqual(r['fills'][0]['requested'],0)
        self.assertAlmostEqual(r['fills'][1]['requested'],100)
    def test_no_volume_no_fills(self):
        f=flat_frame();f['volume']=0.
        r=simulate(f,np.ones(4)/4,config(),'TWAP')
        self.assertEqual(r['metrics']['filled_quantity'],0)
        self.assertIsNone(r['metrics']['execution_vwap'])
    def test_opportunity_cost_sign(self):
        f=flat_frame();f['volume']=0.;f.loc[3,'last']=110.
        for side,expected in [('buy',1000),('sell',-1000)]:
            m=simulate(f,np.ones(4)/4,config(side=side),'TWAP')['metrics']
            self.assertAlmostEqual(m['implementation_shortfall_bps'],expected)
    def test_decomposition_reconciles(self):
        f=flat_frame();f['quote_mid']=[100,101,99,102];f['spread_bps']=3
        c=config().model_copy(update={'impact_bps':8.,'fee_bps':2.,'noise_bps':1.,'quantity':200.})
        for side in ['buy','sell']:
            for p in ['TWAP','VWAP','POV']:
                m=simulate(f,np.ones(4)/4,c.model_copy(update={'side':side}),p,100)['metrics']
                self.assertLess(abs(m['decomposition_error']),1e-8)
    def test_seed_reproducible(self):
        c=config().model_copy(update={'noise_bps':2.})
        self.assertEqual(simulate(flat_frame(),np.ones(4)/4,c,'TWAP'),simulate(flat_frame(),np.ones(4)/4,c,'TWAP'))
    def test_profile_rejects_bad_weights(self):
        with self.assertRaises(ValueError):simulate(flat_frame(),np.ones(4),config(),'VWAP')
    def test_bootstrap_paired_constant(self):
        r=paired_bootstrap([-2,-2,-2]);self.assertEqual(r['ci95_low'],-2);self.assertEqual(r['ci95_high'],-2)
    def test_bootstrap_requires_multiple_windows(self):
        with self.assertRaises(ValueError):paired_bootstrap([1])

class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.m=demo(self.root)
        self.m,self.t,self.q=load(self.root,self.m['id'])
    def tearDown(self):self.tmp.cleanup()
    def cfg(self):
        return config().model_copy(update={'dataset_id':self.m['id']})
    def test_demo_provenance_and_quarantine(self):
        self.assertEqual(self.m['source'],'synthetic_demo');self.assertEqual(self.m['rejected_trade_rows'],2)
        self.assertEqual(len(self.t),2160)
    def test_duplicate_registration_is_idempotent(self):self.assertEqual(self.m['id'],demo(self.root)['id'])
    def test_demo_identity_is_platform_independent(self):
        # Pinned value: CRLF output on Windows previously produced a different content ID.
        self.assertEqual(self.m['id'],'22a2df81ac5154c0')
        for name in ['trades.csv','quotes.csv','raw_trades.csv','raw_quotes.csv','manifest.json']:
            self.assertNotIn(b'\r',(self.root/self.m['id']/name).read_bytes(),name)
    def test_raw_files_stored_byte_for_byte(self):
        text='timestamp,symbol,trade_id,price,quantity\n2025-01-01T00:00:00Z,X,1,1,2\n'
        m=register(self.root,'lf',text)
        self.assertEqual((self.root/m['id']/'raw_trades.csv').read_bytes(),text.encode())
    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):utc('2025-01-01')
    def test_columns_required(self):
        with self.assertRaises(ValueError):read_csv('price\n1\n','trades')
    def test_nonfinite_negative_and_duplicate_quarantine(self):
        s='timestamp,symbol,trade_id,price,quantity\n2025-01-01T00:00:00Z,X,1,1,2\n2025-01-01T00:00:01Z,X,2,nan,2\n2025-01-01T00:00:02Z,X,3,1,-2\n2025-01-01T00:00:00Z,X,1,1,2\n'
        f,b=read_csv(s,'trades');self.assertEqual(len(f),1);self.assertEqual(len(b),3)
    def test_crossed_quote_rejected(self):
        s='timestamp,symbol,bid,ask\n2025-01-01T00:00:00Z,X,1,2\n2025-01-01T00:01:00Z,X,3,2\n'
        f,b=read_csv(s,'quotes');self.assertEqual(len(b),1)
    def test_trade_only_has_no_invented_spread(self):
        f=bars(self.t,None);s=summary(f);self.assertIsNone(s['mean_quoted_spread_bps']);self.assertEqual(s['quote_coverage'],0)
    def test_backward_quote_alignment_and_staleness(self):
        trades=self.t.iloc[:3].copy();quotes=self.q.iloc[:1].copy();quotes.timestamp+=pd.Timedelta(seconds=1)
        self.assertTrue(pd.isna(bars(trades,quotes).quote_mid.iloc[0]))
        quotes.timestamp-=pd.Timedelta(hours=1)
        self.assertTrue(pd.isna(bars(trades,quotes).quote_mid.iloc[0]))
    def test_checksum_failure_detected(self):
        with (self.root/self.m['id']/'trades.csv').open('a') as out:out.write('\n')
        with self.assertRaisesRegex(ValueError,'integrity'):load(self.root,self.m['id'])
    def test_training_cutoff_enforced(self):
        with self.assertRaises(ValueError):prepare(self.t,self.q,self.cfg().model_copy(update={'training_end':'2025-01-10T00:00:00Z'}))
    def test_future_volume_cannot_change_schedule(self):
        c=self.cfg();a,weights,prev=prepare(self.t,self.q,c)
        future=self.t.copy();future.loc[future.timestamp>=utc(c.start),'quantity']*=1000
        b,newweights,_=prepare(future,self.q,c)
        np.testing.assert_array_equal(weights,newweights)
        # The first TWAP request is independent of all current/future realised volume.
        x=simulate(a,weights,c,'TWAP',prev);z=simulate(b,newweights,c,'TWAP',prev)
        self.assertEqual(x['fills'][0]['requested'],z['fills'][0]['requested'])
    def test_window_bounds_rejected(self):
        for end in ['2025-01-09T09:30:00Z','2025-01-10T10:00:00Z','2025-01-09T09:35:01Z']:
            with self.assertRaises(ValueError):prepare(self.t,self.q,self.cfg().model_copy(update={'end':end}))
    def test_batch_shape_and_finite_json(self):
        r=compare(self.t,self.q,self.m,self.cfg(),risk_paths=4)
        self.assertEqual(len(r['results']),3);json.dumps(r,allow_nan=False)
    def test_store_concurrent_idempotence(self):
        db=Store(self.root/'test.sqlite');r={'id':'abc','config':{},'results':[]}
        with concurrent.futures.ThreadPoolExecutor(8) as pool:list(pool.map(db.save,[r]*20))
        self.assertEqual(len(db.list()),1)
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):load(self.root,'../other')

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from marketlens.app import create_app
        cls.tmp=tempfile.TemporaryDirectory();cls.client=TestClient(create_app(cls.tmp.name))
        cls.dataset=cls.client.get('/api/datasets').json()[0]
        cls.c=config().model_copy(update={'dataset_id':cls.dataset['id']}).model_dump()
    @classmethod
    def tearDownClass(cls):cls.client.close();cls.tmp.cleanup()
    def test_health_dashboard_docs(self):
        for url in ['/','/static/app.js','/api/health','/docs','/openapi.json']:self.assertEqual(self.client.get(url).status_code,200)
    def test_invalid_config(self):
        for patch in [{'quantity':-1},{'side':'invalid'},{'participation':.4,'max_participation':.1},{'extra':1}]:
            self.assertEqual(self.client.post('/api/experiments',json={**self.c,**patch}).status_code,422)
    def test_unknown_dataset_and_run(self):
        self.assertEqual(self.client.get('/api/experiments/nope').status_code,404)
        self.assertEqual(self.client.get('/api/datasets/0000000000000000/analytics').status_code,404)
    def test_create_idempotent_export(self):
        a=self.client.post('/api/experiments',json=self.c);self.assertEqual(a.status_code,201)
        r=a.json();b=self.client.post('/api/experiments',json=self.c).json();self.assertEqual(r['id'],b['id'])
        for ext in ['export.json','fills.csv']:self.assertEqual(self.client.get('/api/experiments/'+r['id']+'/'+ext).status_code,200)
        self.assertIn('reference_kind',self.client.get('/api/experiments/'+r['id']+'/fills.csv').text)
    def test_analysis_and_quarantine(self):
        id=self.dataset['id'];a=self.client.get(f'/api/datasets/{id}/analytics').json()
        self.assertEqual(a['summary']['bars'],720)
        self.assertEqual(len(self.client.get(f'/api/datasets/{id}/quarantine').json()['trades']),2)
    def test_malformed_import(self):
        self.assertEqual(self.client.post('/api/datasets',json={'name':'Bad','trades_csv':'foo\n1'}).status_code,422)
    def test_nonoverlap_batch_validation(self):
        w={'start':self.c['start'],'end':self.c['end']}
        self.assertEqual(self.client.post('/api/batches',json={'config':self.c,'windows':[w,w]}).status_code,422)
    def test_batch(self):
        windows=[{'start':f'2025-01-{day}T09:30:00Z','end':f'2025-01-{day}T09:34:00Z'} for day in ['09','10','11']]
        r=self.client.post('/api/batches',json={'config':self.c,'windows':windows});self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['paired_cost_comparisons']['VWAP']['windows'],3)

if __name__=='__main__':unittest.main()

class ArchiveAndRegressionTests(unittest.TestCase):
    def test_binance_timestamp_milliseconds_and_microseconds(self):
        import importlib.util, io, zipfile
        spec=importlib.util.spec_from_file_location('adapter',Path(__file__).parents[1]/'scripts/import_binance.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for timestamp,expected in [('1704704400123','2024-01-08T09:00:00.123000+00:00'),('1735689600010866','2025-01-01T00:00:00.010866+00:00')]:
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w') as archive:archive.writestr('sample.csv',f'1,0.25,10,1,1,{timestamp},false,true\n')
            converted=module.convert(output.getvalue(),'TESTUSDT')
            self.assertIn(expected,converted)
    def test_mixed_fractional_timestamps_roundtrip(self):
        text='timestamp,symbol,trade_id,price,quantity\n2025-01-01T00:00:00.123000Z,X,1,1,1\n2025-01-01T00:00:01Z,X,2,1,1\n'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=register(root,'mixed',text);_,t,_=load(root,m['id']);self.assertEqual(len(t),2)
    def test_nonfinite_config_returns_validation_error(self):
        from marketlens.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(tmp)) as client:
                body=json.dumps(config().model_dump()).replace('"quantity": 40.0','"quantity": NaN')
                response=client.post('/api/experiments',content=body,headers={'Content-Type':'application/json'})
                self.assertEqual(response.status_code,422)
    def test_batch_concurrent_duplicate_requests(self):
        from marketlens.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(tmp)) as client:
                id=client.get('/api/datasets').json()[0]['id'];c=config().model_copy(update={'dataset_id':id}).model_dump()
                with concurrent.futures.ThreadPoolExecutor(4) as pool:
                    responses=list(pool.map(lambda _:client.post('/api/experiments',json=c),range(4)))
                self.assertEqual({r.status_code for r in responses},{201})
                self.assertEqual(len({r.json()['id'] for r in responses}),1)
                self.assertEqual(len(client.get('/api/experiments').json()),1)
    def test_import_quotes_mismatched_symbol(self):
        t='timestamp,symbol,trade_id,price,quantity\n2025-01-01T00:00:00Z,X,1,1,1\n'
        q='timestamp,symbol,bid,ask\n2025-01-01T00:00:00Z,Y,1,2\n'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):register(Path(tmp),'bad',t,q)
