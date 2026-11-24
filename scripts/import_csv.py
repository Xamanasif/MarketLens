import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marketlens.data import register
p=argparse.ArgumentParser(description='Validate and register a single-symbol market CSV dataset')
p.add_argument('trades');p.add_argument('--quotes');p.add_argument('--name',required=True);p.add_argument('--description',default='User-supplied dataset; provenance unverified.');p.add_argument('--home',default='data')
a=p.parse_args()
result=register(Path(a.home)/'datasets',a.name,Path(a.trades).read_text(),Path(a.quotes).read_text() if a.quotes else None,'user_supplied',a.description)
print(result['id'])
