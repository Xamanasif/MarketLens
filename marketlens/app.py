import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from . import __version__
from .analytics import bars, records, summary
from .data import demo, load, manifest, register
from .engine import compare, paired_bootstrap
from .models import BatchRequest, Config, ImportRequest
from .store import Store

log=logging.getLogger('marketlens')

def create_app(home=None):
    home=Path(home or os.environ.get('MARKETLENS_HOME',Path(__file__).resolve().parent.parent/'data'))
    root=home/'datasets';root.mkdir(parents=True,exist_ok=True)
    store=Store(home/'marketlens.sqlite3')
    demo(root)
    app=FastAPI(title='MarketLens',version=__version__,description='Historical market analytics and explicitly simulated execution research. Local single-user workbench.')
    app.state.home=home
    app.state.store=store
    app.state.requests=0
    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')

    @app.middleware('http')
    async def observe(request: Request,call_next):
        started=time.perf_counter()
        if request.method=='POST':
            size=request.headers.get('content-length')
            if not size or not size.isdigit() or int(size)>13_000_000:
                return JSONResponse({'detail':'POST requires Content-Length <= 13 MB'},status_code=413)
        response=await call_next(request)
        elapsed=time.perf_counter()-started
        app.state.requests+=1
        response.headers['X-Process-Time']=f'{elapsed:.6f}'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        log.info('%s %s %s %.3fs',request.method,request.url.path,response.status_code,elapsed)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_schema(request,exc):
        return JSONResponse({'detail':'; '.join(e['msg'] for e in exc.errors())},status_code=422)

    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc):return JSONResponse({'detail':'Dataset or artifact not found'},status_code=404)
    @app.exception_handler(KeyError)
    async def unknown(request,exc):return JSONResponse({'detail':'Experiment not found'},status_code=404)

    @app.get('/')
    def index():return FileResponse(static/'index.html')
    @app.get('/api/health')
    def health():return {'status':'ok','version':__version__,'mode':'local-research','requests':app.state.requests}
    @app.get('/api/datasets')
    def datasets():return [manifest(root,p.name) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith('.')]
    @app.post('/api/datasets',status_code=201)
    def ingest(req:ImportRequest):return register(root,req.name,req.trades_csv,req.quotes_csv,'user_supplied',req.description)
    @app.get('/api/datasets/{dataset_id}/analytics')
    def analytics(dataset_id:str):
        m,t,q=load(root,dataset_id)
        f=bars(t,q)
        return {'dataset':m,'summary':summary(f),'bars':records(f)}
    @app.get('/api/datasets/{dataset_id}/quarantine')
    def quarantine(dataset_id:str):
        manifest(root,dataset_id)
        return json.loads((root/dataset_id/'quarantine.json').read_text())
    @app.post('/api/experiments',status_code=201)
    def experiment(config:Config):
        m,t,q=load(root,config.dataset_id)
        return store.save(compare(t,q,m,config))
    @app.get('/api/experiments')
    def history():return store.list()
    @app.get('/api/experiments/{id}')
    def detail(id:str):return store.get(id)
    @app.get('/api/experiments/{id}/export.json')
    def export_json(id:str):
        result=store.get(id)
        return Response(json.dumps(result,indent=2,allow_nan=False),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="marketlens-{id}.json"'})
    @app.get('/api/experiments/{id}/fills.csv')
    def export_csv(id:str):
        result=store.get(id);rows=[r for x in result['results'] for r in x['fills']]
        out=io.StringIO();w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="fills-{id}.csv"'})
    @app.post('/api/batches')
    def batch(req:BatchRequest):
        # Batch comparisons use non-overlapping windows. Block resampling is at whole-window level.
        from .data import utc
        intervals=[]
        for w in req.windows:
            if set(w)!={'start','end'}:raise ValueError('Each window needs only start and end')
            a,b=utc(w['start']),utc(w['end'])
            if a>=b:raise ValueError('Invalid batch window')
            intervals.append((a,b))
        ordered=sorted(intervals)
        if any(b>c for (a,b),(c,d) in zip(ordered,ordered[1:])):raise ValueError('Batch windows must not overlap')
        m,t,q=load(root,req.config.dataset_id)
        results=[]
        for a,b in intervals:
            c=Config(**{**req.config.model_dump(),'start':a.isoformat(),'end':b.isoformat()})
            results.append(store.save(compare(t,q,m,c,risk_paths=32)))
        comparisons={}
        for policy in ('VWAP','POV'):
            diff=[]
            for r in results:
                metrics={x['metrics']['policy']:x['metrics'] for x in r['results']}
                diff.append(metrics[policy]['implementation_shortfall_bps']-metrics['TWAP']['implementation_shortfall_bps'])
            comparisons[policy]=paired_bootstrap(diff,req.config.seed)
        return {'experiment_ids':[r['id'] for r in results],'paired_cost_comparisons':comparisons,
                'limitation':'Few or serially dependent sessions produce unreliable confidence intervals. Descriptive comparison, not strategy selection evidence.'}
    return app

app=create_app()
