"""Reproducible matched-window evaluation. No training on execution windows."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from marketlens.data import demo, load
from marketlens.models import Config
from marketlens.engine import compare, paired_bootstrap
from marketlens.store import Store


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--home',default='data');parser.add_argument('--output',default='reports/evaluation.json')
    args=parser.parse_args();home=Path(args.home);m=demo(home/'datasets');m,t,q=load(home/'datasets',m['id']);store=Store(home/'marketlens.sqlite3')
    runs=[]
    # Training sessions Jan 6-8; matched out-of-training sessions Jan 9-11.
    for day in ['09','10','11']:
        for side in ['buy','sell']:
            for qty in [500,2500]:
                c=Config(dataset_id=m['id'],start=f'2025-01-{day}T09:30:00Z',end=f'2025-01-{day}T11:30:00Z',training_end='2025-01-09T00:00:00Z',side=side,quantity=qty)
                r=compare(t,q,m,c);store.save(r);runs.append(r)
    # Resample sessions, averaging configurations within session to avoid pseudoreplication.
    session_differences={p:[] for p in ['VWAP','POV']}
    for day in ['09','10','11']:
        subset=[r for r in runs if r['config']['start'].startswith('2025-01-'+day)]
        for p in session_differences:
            values=[]
            for r in subset:
                metrics={x['metrics']['policy']:x['metrics'] for x in r['results']}
                values.append(metrics[p]['implementation_shortfall_bps']-metrics['TWAP']['implementation_shortfall_bps'])
            session_differences[p].append(float(np.mean(values)))
    report={'data_source':'synthetic_demo','dataset_id':m['id'],'dataset_hashes':m['hashes'],
            'training_end':'2025-01-09T00:00:00Z','execution_sessions':3,'matched_configurations':len(runs),
            'policy_evaluations':len(runs)*3,'code_sha256':runs[0]['code_sha256'],
            'paired_session_bootstrap':{p:paired_bootstrap(v) for p,v in session_differences.items()},
            'warning':'Synthetic software demonstration. Three independent generated sessions are far too few for strong inferential claims; no real-market superiority established.',
            'runs':[{'id':r['id'],'config':r['config'],'metrics':[x['metrics'] for x in r['results']]} for r in runs]}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:report[k] for k in ['execution_sessions','matched_configurations','policy_evaluations','data_source']},indent=2))
if __name__=='__main__':main()
