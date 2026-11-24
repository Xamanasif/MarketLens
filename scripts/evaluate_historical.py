"""Run frozen matched comparisons on the bundled public trade-only sample."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from marketlens.data import load
from marketlens.models import Config
from marketlens.engine import compare, paired_bootstrap
from marketlens.store import Store
p=argparse.ArgumentParser();p.add_argument('--home',default='data');p.add_argument('--dataset-id');p.add_argument('--output',default='reports/historical_evaluation.json');a=p.parse_args()
home=Path(a.home);root=home/'datasets'
if a.dataset_id:id=a.dataset_id
else:
    found=[]
    for folder in root.iterdir():
        if folder.name.startswith('.'):continue
        meta=json.loads((folder/'manifest.json').read_text())
        if meta['source']=='public_archive' and len(meta['sessions'])>=4:found.append(meta['id'])
    if not found:raise SystemExit('Import a public dataset with >= 4 sessions first; see README')
    id=sorted(found)[0]
m,t,q=load(root,id);sessions=m['sessions'];holdouts=sessions[2:];cut=holdouts[0]+'T00:00:00Z'
store=Store(home/'marketlens.sqlite3');runs=[]
for day in holdouts:
    for side in ['buy','sell']:
        for quantity in [500,2500]:
            c=Config(dataset_id=id,start=day+'T09:30:00Z',end=day+'T11:30:00Z',training_end=cut,side=side,quantity=quantity)
            r=compare(t,q,m,c);store.save(r);runs.append(r)
differences={x:[] for x in ['VWAP','POV']}
for day in holdouts:
    selected=[r for r in runs if r['config']['start'].startswith(day)]
    for policy in differences:
        delta=[]
        for r in selected:
            metrics={x['metrics']['policy']:x['metrics'] for x in r['results']}
            delta.append(metrics[policy]['implementation_shortfall_bps']-metrics['TWAP']['implementation_shortfall_bps'])
        differences[policy].append(float(np.mean(delta)))
report={'source':'public_archive','dataset':m,'training_sessions':sessions[:2],
        'holdout_sessions':holdouts,'matched_configurations':len(runs),'policy_evaluations':len(runs)*3,
        'code_sha256':runs[0]['code_sha256'],'paired_session_bootstrap':{p:paired_bootstrap(x) for p,x in differences.items()},
        'warning':'Observed historical trade inputs; simulated fills, spreads, impact and fees. Two evaluation sessions are insufficient for inferential claims or a trading-performance conclusion. No out-of-sample model selection is claimed.',
        'runs':[{'id':r['id'],'config':r['config'],'metrics':[x['metrics'] for x in r['results']]} for r in runs]}
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2,allow_nan=False))
print(json.dumps({'dataset':id,'trades':m['trade_rows'],'sessions':sessions,'matched_configurations':len(runs),'policy_evaluations':len(runs)*3},indent=2))
