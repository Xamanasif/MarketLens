"""Optional public archive adapter. Network required. Never infers bid/ask from trades."""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marketlens.data import register


def convert(blob,symbol,max_rows=100000):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members=[x for x in z.infolist() if x.filename.endswith('.csv')]
        if len(members)!=1 or members[0].file_size>100_000_000:
            raise ValueError('Archive must contain one CSV <= 100 MB uncompressed')
        output=io.StringIO();w=csv.writer(output);w.writerow(['timestamp','symbol','trade_id','price','quantity'])
        count=0
        with z.open(members[0]) as f:
            for row in csv.reader(io.TextIOWrapper(f)):
                if not row or row[0] in ['agg_trade_id','aggregate_trade_id']:continue
                if count>=max_rows:raise ValueError('Archive exceeds row limit; choose a less active symbol/date or prepare bounded CSV slices explicitly')
                ts=int(row[5]);unit=1_000_000 if ts>=10**15 else 1000
                t=(datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(microseconds=ts if unit==1_000_000 else ts*1000)).isoformat()
                w.writerow([t,symbol,row[0],row[1],row[2]]);count+=1
    return output.getvalue()


def fetch(url,limit):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'MarketLens/1.0 research'}),timeout=45) as f:
        content=f.read(limit+1)
    if len(content)>limit:raise ValueError('Download exceeds size cap')
    return content


def main():
    p=argparse.ArgumentParser();p.add_argument('--symbol',default='BATUSDT');p.add_argument('--date',required=True,action='append',help='Repeat for multiple dates to construct a prior-session profile');p.add_argument('--home',default='data');p.add_argument('--start-time',default='00:00');p.add_argument('--end-time',default='24:00');p.add_argument('--archive',help='Optional local ZIP for exactly one --date');p.add_argument('--checksum',help='Expected SHA256 for a local ZIP')
    a=p.parse_args()
    if not re.fullmatch('[A-Z0-9]{5,20}',a.symbol):raise ValueError('Invalid symbol')
    if len(a.date)>10 or len(set(a.date))!=len(a.date):raise ValueError('Use 1-10 unique dates')
    if a.archive and len(a.date)!=1:raise ValueError('Local ZIP supports one date')
    home=Path(a.home);raw=home/'source_archives';raw.mkdir(parents=True,exist_ok=True)
    pieces=[];sources=[]
    for day_text in sorted(a.date):
        day=date.fromisoformat(day_text)
        url=f'https://data.binance.vision/data/spot/daily/aggTrades/{a.symbol}/{a.symbol}-aggTrades-{day}.zip'
        if a.archive:
            if not a.checksum:raise ValueError('Local archive requires --checksum')
            blob=Path(a.archive).read_bytes();expected=a.checksum
        else:
            cached=raw/f'{a.symbol}-{day}.zip'
            blob=cached.read_bytes() if cached.exists() else fetch(url,25_000_000)
            expected=fetch(url+'.CHECKSUM',1000).decode().split()[0]
        actual=hashlib.sha256(blob).hexdigest()
        if not re.fullmatch('[a-fA-F0-9]{64}',expected) or actual!=expected.lower():raise ValueError('Archive SHA256 mismatch')
        csv_text=convert(blob,a.symbol)
        rows=list(csv.reader(io.StringIO(csv_text)));out=io.StringIO();writer=csv.writer(out);writer.writerow(rows[0])
        for row in rows[1:]:
            if a.start_time<=row[0][11:16]<a.end_time:writer.writerow(row)
        csv_text=out.getvalue()
        (raw/f'{a.symbol}-{day}.zip').write_bytes(blob)
        sources.append({'source_url':url,'sha256':actual,'date':str(day)})
        pieces.append(csv_text if not pieces else csv_text.split('\n',1)[1])
    merged=''.join(pieces)
    m=register(home/'datasets',f'{a.symbol} historical aggregate trades ({len(pieces)} sessions)',merged,None,'public_archive',
        'Binance public trade-only archives. Original ZIP SHA256 verified against published checksums. No observed quotes; no order-book depth. Acquisition manifest in data/source_archives. Review source terms. UTC window '+a.start_time+' to '+a.end_time+'.')
    (raw/f'{m["id"]}-sources.json').write_text(json.dumps({'dataset_id':m['id'],'sources':sources},indent=2))
    print(m['id'])
if __name__=='__main__':main()
