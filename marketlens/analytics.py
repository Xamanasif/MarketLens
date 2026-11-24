"""One-minute liquidity and volatility analytics, without inventing bid/ask data."""
import numpy as np
import pandas as pd


def bars(trades, quotes=None, max_age=120):
    t = trades.copy()
    t['bucket'] = t.timestamp.dt.floor('min')
    t['notional'] = t.price*t.quantity
    g = t.groupby('bucket', sort=True)
    frame = g.agg(volume=('quantity','sum'), notional=('notional','sum'), trades=('price','size'),
                  first=('price','first'), last=('price','last'), high=('price','max'), low=('price','min'))
    # Fill empty minutes only within each UTC session, not overnight.
    parts = []
    for _, session in frame.groupby(frame.index.date):
        idx = pd.date_range(session.index.min(), session.index.max(), freq='min')
        session = session.reindex(idx)
        session['last'] = session['last'].ffill()
        session['first'] = session['first'].fillna(session['last'])
        for col in ['high','low']:
            session[col] = session[col].fillna(session['last'])
        session[['volume','notional','trades']] = session[['volume','notional','trades']].fillna(0)
        parts.append(session)
    frame = pd.concat(parts).rename_axis('timestamp').reset_index()
    frame['vwap'] = np.where(frame.volume>0,frame.notional/frame.volume.replace(0,np.nan),frame['last'])
    frame['quote_mid'] = np.nan
    frame['spread_bps'] = np.nan
    if quotes is not None:
        q = quotes.rename(columns={'timestamp':'quote_time'}).sort_values('quote_time')
        joined = pd.merge_asof(frame[['timestamp']], q, left_on='timestamp',right_on='quote_time',
                               direction='backward',tolerance=pd.Timedelta(seconds=max_age))
        frame['quote_mid']=(joined.bid+joined.ask)/2
        frame['spread_bps']=(joined.ask-joined.bid)/frame.quote_mid*10000
    frame['return_bps'] = frame.groupby(frame.timestamp.dt.date)['last'].transform(lambda s: np.log(s/s.shift()).fillna(0)*10000)
    return frame


def summary(frame):
    ret=frame.return_bps.to_numpy()
    usable=frame[frame.volume>0]
    spread=frame.spread_bps.dropna()
    minute=frame.timestamp.dt.strftime('%H:%M')
    grouped=frame.assign(minute=minute).groupby('minute').agg(mean_volume=('volume','mean'),
            mean_abs_return_bps=('return_bps', lambda x: float(np.abs(x).mean())), mean_spread_bps=('spread_bps','mean')).reset_index()
    grouped=grouped.astype(object).where(pd.notna(grouped),None)
    return {'bars':len(frame),'total_volume':float(frame.volume.sum()),'trades':int(frame.trades.sum()),
            'market_vwap':float(frame.notional.sum()/frame.volume.sum()),
            'realized_volatility_bps':float(np.sqrt(np.sum(ret**2))),
            'minute_return_std_bps':float(np.std(ret)),
            'mean_quoted_spread_bps':None if spread.empty else float(spread.mean()),
            'quote_coverage':float(frame.quote_mid.notna().mean()),
            'liquidity_proxy':'Observed traded volume; not order-book depth',
            'illiquidity_proxy':None if usable.empty else float((usable.return_bps.abs()/usable.notional).mean()),
            'intraday':grouped.to_dict('records')}


def volume_profile(frame, training_end):
    training = frame[frame.timestamp < training_end].copy()
    if training.empty:
        raise ValueError('No training observations before training_end')
    profile=training.assign(minute=training.timestamp.dt.strftime('%H:%M')).groupby('minute').volume.mean()
    if profile.sum()<=0:
        raise ValueError('Training profile has zero volume')
    return profile


def records(frame):
    copy=frame.copy()
    copy['timestamp']=copy.timestamp.map(lambda t:t.isoformat())
    return copy.astype(object).where(pd.notna(copy),None).to_dict('records')
