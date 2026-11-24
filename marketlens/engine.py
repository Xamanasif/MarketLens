"""Causal policy decisions on a fixed historical tape; fills are simulated."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .analytics import bars, records, volume_profile
from .data import utc

POLICIES = ('TWAP','VWAP','POV')
ENGINE_VERSION = '1.0.0'

def code_hash():
    h=hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()


def prepare(trades, quotes, config):
    start,end,cut=map(utc,[config.start,config.end,config.training_end])
    if start>=end or cut>start:
        raise ValueError('Require training_end <= start < end')
    if start != start.floor('min') or end != end.floor('min'):
        raise ValueError('Start/end must lie on minute boundaries')
    if (end-start)>pd.Timedelta(hours=6) or start.date()!=(end-pd.Timedelta(nanoseconds=1)).date():
        raise ValueError('Choose one UTC session window of at most six hours')
    all_bars=bars(trades,quotes,config.quote_max_age_seconds)
    selected=all_bars[(all_bars.timestamp>=start)&(all_bars.timestamp<end)].copy()
    expected=int((end-start).total_seconds()/60)
    if len(selected)!=expected:
        raise ValueError('Selected interval is not fully covered by dataset minute bars')
    if selected.volume.sum()<=0:
        raise ValueError('Selected window has no market volume')
    profile=volume_profile(all_bars,cut)
    mins=selected.timestamp.dt.strftime('%H:%M')
    # Never substitute evaluation volume for missing profile buckets.
    if any(m not in profile.index for m in mins):
        raise ValueError('Training profile lacks minute buckets for this execution window')
    weights=np.array([float(profile.loc[m]) for m in mins])
    if weights.sum()<=0:
        raise ValueError('Training window profile is empty')
    previous=all_bars[all_bars.timestamp<start]
    prev_volume=0.
    if not previous.empty and (start-previous.timestamp.iloc[-1])==pd.Timedelta(minutes=1):
        prev_volume=float(previous.volume.iloc[-1])
    return selected.reset_index(drop=True),weights/weights.sum(),prev_volume


def simulate(frame, profile, config, policy, previous_volume=0., noise=None):
    if policy not in POLICIES:
        raise ValueError('Unknown execution policy')
    n=len(frame)
    if not n or len(profile)!=n or not np.isfinite(profile).all() or min(profile)<0 or abs(sum(profile)-1)>1e-8:
        raise ValueError('Invalid schedule profile')
    rng=np.random.default_rng(config.seed)
    noise=rng.normal(0,config.noise_bps,n) if noise is None else np.asarray(noise)
    sign=1 if config.side=='buy' else -1
    arrival=float(frame.quote_mid.iloc[0]) if pd.notna(frame.quote_mid.iloc[0]) else float(frame['first'].iloc[0])
    remaining=config.quantity
    fills=[]
    fees=timing=spread_cost=impact_cost=noise_cost=executed=0.
    weights=np.ones(n)/n if policy=='TWAP' else profile
    cumulative=np.cumsum(weights)*config.quantity
    for i,row in enumerate(frame.itertuples(index=False)):
        filled=config.quantity-remaining
        request=max(0.,cumulative[i]-filled) if policy!='POV' else config.participation*previous_volume
        capacity=config.max_participation*float(row.volume)
        qty=min(remaining,request,capacity)
        # POV observes only the preceding completed minute; capacity is a fill-side constraint.
        previous_volume=float(row.volume)
        base=float(row.quote_mid) if pd.notna(row.quote_mid) else float(row.vwap)
        spread=float(row.spread_bps) if pd.notna(row.spread_bps) else config.assumed_spread_bps
        participation=qty/row.volume if row.volume>0 else 0.
        impact=config.impact_bps*math.sqrt(participation)
        movement=float(noise[i])
        price=base*(1+sign*(spread/2+impact+movement)/10000)
        fee=qty*price*config.fee_bps/10000
        fees+=fee; executed+=qty*price
        timing+=sign*qty*(base-arrival)
        spread_cost+=qty*base*spread/2/10000
        impact_cost+=qty*base*impact/10000
        noise_cost+=qty*base*movement/10000
        remaining=max(0.,remaining-qty)
        fills.append({'timestamp':row.timestamp.isoformat(),'policy':policy,'market_volume':float(row.volume),
                      'requested':float(request),'quantity':float(qty),'price':float(price) if qty>0 else None,
                      'reference_price':base,'reference_kind':'quote_mid' if pd.notna(row.quote_mid) else 'bar_vwap_proxy',
                      'spread_bps':spread,'spread_kind':'observed_quote' if pd.notna(row.quote_mid) else 'assumed',
                      'participation':float(participation),'impact_bps':float(impact),'fee':float(fee),
                      'cumulative_quantity':float(config.quantity-remaining),'remaining':float(remaining)})
    filled=config.quantity-remaining
    terminal=float(frame['last'].iloc[-1])
    opportunity=sign*remaining*(terminal-arrival)
    gross=sign*(executed-filled*arrival)
    total=gross+fees+opportunity
    denom=config.quantity*arrival
    market_vwap=float(frame.notional.sum()/frame.volume.sum()) if frame.volume.sum()>0 else None
    avg=executed/filled if filled>0 else None
    metric={'policy':policy,'filled_quantity':float(filled),'unfilled_quantity':float(remaining),
            'completion_pct':float(filled/config.quantity*100),'arrival_price':arrival,'terminal_price':terminal,
            'execution_vwap':avg,'market_vwap':market_vwap,
            'vwap_slippage_bps':None if avg is None else float(sign*(avg-market_vwap)/market_vwap*10000),
            'filled_arrival_slippage_bps':None if avg is None else float(sign*(avg-arrival)/arrival*10000),
            'implementation_shortfall_bps':float(total/denom*10000),
            'implementation_shortfall_cash':float(total),'fees_cash':float(fees),
            'timing_cash':float(timing),'spread_cash':float(spread_cost),'impact_cash':float(impact_cost),
            'noise_cash':float(noise_cost),'opportunity_cash':float(opportunity),
            'gross_execution_cash':float(gross),
            'decomposition_error':float(total-(timing+spread_cost+impact_cost+noise_cost+fees+opportunity))}
    return {'metrics':metric,'fills':fills}


def compare(trades,quotes,manifest,config,risk_paths=32):
    frame,profile,prev=prepare(trades,quotes,config)
    rng=np.random.default_rng(config.seed)
    scenarios=rng.normal(0,config.noise_bps,(risk_paths,len(frame)))
    results=[]
    for policy in POLICIES:
        result=simulate(frame,profile,config,policy,prev)
        dist=np.array([simulate(frame,profile,config,policy,prev,n)['metrics']['implementation_shortfall_bps'] for n in scenarios])
        result['risk']={'paths':risk_paths,'mean_bps':float(dist.mean()),'std_bps':float(dist.std()),
                        'p05_bps':float(np.quantile(dist,.05)),'p95_bps':float(np.quantile(dist,.95)),
                        'label':'Conditional simulated fill-noise sensitivity on this fixed market path; not market VaR.'}
        results.append(result)
    conf=config.model_dump()
    sha=code_hash()
    experiment_id=hashlib.sha256(json.dumps([manifest['hashes'],conf,sha,ENGINE_VERSION,risk_paths],sort_keys=True).encode()).hexdigest()[:24]
    return {'id':experiment_id,'engine_version':ENGINE_VERSION,'code_sha256':sha,'config':conf,
            'dataset':manifest,'profile':{'training_end_exclusive':config.training_end,
            'method':'Mean volume by UTC minute, restricted to observations strictly before training_end',
            'weights':profile.tolist()},'market_bars':records(frame),'results':results,
            'assumptions':['All fills and costs are simulated, even with historical market inputs.',
             'VWAP uses prior-session volume profiles; evaluation VWAP is a benchmark only.',
             'POV requests use preceding-minute volume; fill capacity uses current-minute volume.',
             'Quotes are backward as-of matched at minute start with a staleness limit.',
             'Missing quotes use minute VWAP as an explicit fill-price proxy and an assumed spread.',
             'Temporary impact does not alter the historical tape; queue position and permanent impact are absent.',
             'Unfilled quantity is marked to the last observed trade price and is never silently force-filled.',
             'Training profile cut-off is enforced; evaluation windows are descriptive research, not evidence of profitable trading.']}


def paired_bootstrap(values, seed=42, draws=2000):
    x=np.asarray(values,dtype=float)
    if len(x)<2:
        raise ValueError('At least two matched windows required')
    rng=np.random.default_rng(seed)
    means=x[rng.integers(0,len(x),(draws,len(x)))].mean(axis=1)
    return {'mean_difference_bps':float(x.mean()),'ci95_low':float(np.quantile(means,.025)),
            'ci95_high':float(np.quantile(means,.975)),'windows':len(x),'draws':draws,
            'interpretation':'POV/VWAP minus TWAP: negative means lower cost. Resamples whole paired windows; assumes independent windows.'}
