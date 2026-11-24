"""CSV boundary, quarantine, content-addressed immutable data, synthetic fixtures."""
import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np
import pandas as pd

MAX_ROWS = 100_000

def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError('Timestamps must include a timezone (UTC Z or an explicit offset)')
    return t.tz_convert('UTC')

def read_csv(text: str, kind: str):
    required = ['timestamp', 'symbol', 'trade_id', 'price', 'quantity'] if kind == 'trades' else ['timestamp', 'symbol', 'bid', 'ask']
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
        raise ValueError(f'{kind}: required columns: {", ".join(required)}')
    good, rejected, seen = [], [], set()
    for line, row in enumerate(reader, 2):
        if line > MAX_ROWS + 1:
            raise ValueError(f'{kind}: maximum {MAX_ROWS:,} rows per import')
        try:
            t = utc(row['timestamp'])
            symbol = row['symbol'].strip()
            if not symbol or len(symbol) > 32:
                raise ValueError('invalid symbol')
            out = {'timestamp': t.isoformat(), 'symbol': symbol}
            if kind == 'trades':
                trade_id = row['trade_id'].strip()
                if not trade_id:
                    raise ValueError('missing trade_id')
                out.update(trade_id=trade_id, price=float(row['price']), quantity=float(row['quantity']))
                if not np.isfinite([out['price'], out['quantity']]).all() or min(out['price'], out['quantity']) <= 0:
                    raise ValueError('price and quantity must be finite and positive')
                key = (symbol, trade_id)
            else:
                out.update(bid=float(row['bid']), ask=float(row['ask']))
                if not np.isfinite([out['bid'], out['ask']]).all() or out['bid'] <= 0 or out['ask'] < out['bid']:
                    raise ValueError('quotes must be finite, positive and not crossed')
                key = (symbol, t.isoformat())
            if key in seen:
                raise ValueError('duplicate trade ID or quote timestamp')
            seen.add(key)
            good.append(out)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            rejected.append({'line': line, 'reason': str(exc), 'row': row})
    if not good:
        raise ValueError(f'{kind}: no valid rows')
    frame = pd.DataFrame(good).sort_values(['timestamp', 'symbol'], kind='stable').reset_index(drop=True)
    if frame.symbol.nunique() != 1:
        raise ValueError('Import one symbol per dataset; multi-symbol files must be separated')
    return frame, rejected

def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def register(root: Path, name, trades_text, quotes_text=None, source='user_supplied', description=''):
    trades, bad = read_csv(trades_text, 'trades')
    quotes, badq = read_csv(quotes_text, 'quotes') if quotes_text else (None, [])
    if quotes is not None and quotes.symbol.iloc[0] != trades.symbol.iloc[0]:
        raise ValueError('Trade and quote symbols must match')
    raw = json.dumps([name, trades_text, quotes_text, source, description], ensure_ascii=True).encode()
    dataset_id = hashlib.sha256(raw).hexdigest()[:16]
    folder = root / dataset_id
    if folder.exists():
        return manifest(root, dataset_id)
    # Unique staging directory + atomic rename prevents partially readable datasets.
    import tempfile, shutil
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.import-', dir=root))
    try:
        # Explicit LF line endings keep content hashes identical across operating systems.
        trades.to_csv(stage / 'trades.csv', index=False, lineterminator='\n')
        if quotes is not None:
            quotes.to_csv(stage / 'quotes.csv', index=False, lineterminator='\n')
        (stage / 'quarantine.json').write_text(json.dumps({'trades': bad, 'quotes': badq}, indent=2), newline='')
        (stage / 'raw_trades.csv').write_text(trades_text, newline='')
        if quotes_text:
            (stage / 'raw_quotes.csv').write_text(quotes_text, newline='')
        hashes = {p.name: digest(p) for p in stage.iterdir()}
        m = {'id': dataset_id, 'name': name, 'symbol': trades.symbol.iloc[0], 'source': source,
             'description': description, 'trade_rows': len(trades), 'quote_rows': 0 if quotes is None else len(quotes),
             'rejected_trade_rows': len(bad), 'rejected_quote_rows': len(badq),
             'start': trades.timestamp.iloc[0], 'end': trades.timestamp.iloc[-1], 'hashes': hashes,
             'sessions': sorted(pd.to_datetime(trades.timestamp, utc=True, format="ISO8601").dt.strftime('%Y-%m-%d').unique().tolist())}
        (stage / 'manifest.json').write_text(json.dumps(m, indent=2), newline='')
        try:
            stage.rename(folder)
        except OSError:
            if not folder.exists():
                raise
        return manifest(root, dataset_id)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

def manifest(root, dataset_id):
    if len(dataset_id) != 16 or any(c not in '0123456789abcdef' for c in dataset_id):
        raise ValueError('Invalid dataset ID')
    return json.loads((root / dataset_id / 'manifest.json').read_text())

def load(root, dataset_id):
    m = manifest(root, dataset_id)
    folder = root / dataset_id
    for filename, checksum in m['hashes'].items():
        if digest(folder / filename) != checksum:
            raise ValueError(f'Dataset integrity check failed: {filename}')
    trades = pd.read_csv(folder / 'trades.csv', dtype={'trade_id': str})
    trades.timestamp = pd.to_datetime(trades.timestamp, utc=True, format="ISO8601")
    quotes = pd.read_csv(folder / 'quotes.csv') if m['quote_rows'] else None
    if quotes is not None:
        quotes.timestamp = pd.to_datetime(quotes.timestamp, utc=True, format="ISO8601")
    return m, trades, quotes

def demo(root):
    rng = np.random.default_rng(20261124)
    trades, quotes = [], []
    price = 100.
    for day in range(6):
        start = pd.Timestamp('2025-01-06T09:30:00Z') + pd.Timedelta(days=day)
        for minute in range(120):
            # Explicit synthetic regimes: drift and changing liquidity/volatility.
            shock = rng.normal(0, .0005 * (2.5 if 45 <= minute < 70 else 1))
            price *= np.exp(shock + (0.00015 if day % 2 == 0 else -0.0001))
            volume = float(rng.lognormal(3.9, .35) * (1.8 if minute < 20 or minute > 95 else .7))
            t = start + pd.Timedelta(minutes=minute)
            spread = price * (.0003 if 45 <= minute < 70 else .0001)
            quotes.append({'timestamp': t.isoformat(), 'symbol': 'DEMO', 'bid': round(price-spread/2, 6), 'ask': round(price+spread/2, 6)})
            for j in range(3):
                trades.append({'timestamp': (t + pd.Timedelta(seconds=10+j*15)).isoformat(), 'symbol': 'DEMO',
                               'trade_id': f'{day}-{minute}-{j}', 'price': round(price+rng.normal(0,spread/5),6),
                               'quantity': round(volume/3,6)})
    # Intentional invalid records exercise quarantine without changing valid history.
    trades.append(dict(trades[0]))
    trades.append({'timestamp': start.isoformat(), 'symbol': 'DEMO', 'trade_id': 'bad-negative', 'price': -1, 'quantity': 2})
    return register(root, 'Synthetic six-session market demo', pd.DataFrame(trades).to_csv(index=False, lineterminator='\n'),
                    pd.DataFrame(quotes).to_csv(index=False, lineterminator='\n'), 'synthetic_demo',
                    'Generated seed 20261124; prices, trades and quotes are synthetic. Not an exchange dataset.')
