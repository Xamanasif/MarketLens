# Numerical methodology

## Timing contract

Trades are grouped into one-minute intervals [t, t+1 minute). Prices/volume from that interval are outcomes available to the replay simulator; the scheduling policy does not consume their realised volume. At t:

- TWAP chooses a cumulative target Q × elapsed bucket fraction.
- Historical-profile VWAP chooses a cumulative target Q × cumulative prior-session expected-volume weight.
- POV requests p × volume of the immediately preceding completed minute, or zero when no preceding adjacent minute exists.

TWAP/VWAP request the positive difference between cumulative target and already-filled quantity. All policies share the same capacity cap c × current interval market volume and remaining parent quantity. Unfilled target can catch up only subject to later capacity. A six-hour, single-session ceiling bounds compute. No silent end-of-window sweep is used.

The VWAP profile uses mean volume by UTC minute from all bars strictly before `training_end`; selected bucket weights are renormalized within the chosen execution window. Empty minutes within a session are retained with zero volume. Overnight gaps are not inserted. The application validates training availability for all requested minute buckets. Select a cutoff before the earliest evaluation window; a temporal split is enforced, not proof of independent model selection.

## Reference prices and quotes

With quotes, use the last available quote at or before t, aged no more than the configured tolerance. Spread in bps is 10,000 × (ask − bid)/mid. Mid = (bid+ask)/2. Quotes do not imply displayed depth or fill certainty.

Without quotes, use the completed minute's trade VWAP as an explicitly retrospective *fill-price proxy*. Arrival is the first observed trade price of the first minute when no initial quote is available. This is a coarse bar replay, not a faithful order-book simulator. Never claim that assumed spread is measured from historical trades.

## Fill model

For side s = +1 buy / −1 sell, minute executed quantity q, market volume V and reference P:

- participation = q/V (zero if V=0)
- temporary impact bps = impact coefficient × sqrt(participation)
- noise bps = seeded Normal(0, noise sigma)
- fill price = P × [1 + s × (spread bps/2 + impact bps + noise bps)/10,000]
- fee cash = q × fill price × fee bps/10,000

The same per-minute noise path is used for all policy comparisons at a seed. Randomness does not affect scheduling quantities. No permanent impact, queue position, matching-engine priority, latency, cancellation or feedback onto future market prices is modelled.

## Cost accounting

Let A be arrival price, T final observed trade price, F total filled quantity, U = Q−F, E = sum(q × fill price).

- Gross execution cost = s × (E − F × A)
- Opportunity cost = s × U × (T − A)
- Total implementation shortfall = gross execution cost + fee cash + opportunity cost
- IS bps = 10,000 × total shortfall / (Q × A)
- Filled arrival slippage = 10,000 × s × (execution VWAP − A)/A
- VWAP slippage = 10,000 × s × (execution VWAP − market VWAP)/market VWAP

Execution VWAP and filled-only slippage are null when F=0. No-fill orders still have opportunity cost. Positive shortfall is adverse cost for either side. Negative shortfall is possible with favorable market movement. Fees are nonnegative. Cost decomposition separates timing, half-spread, temporary impact, fill noise, fees and opportunity; a residual check detects accounting errors.

## Liquidity, intraday and volatility analytics

The dashboard displays traded volume, count, dollar/quote-currency notional, OHLC/VWAP, quoted spread coverage, intraday mean volume, intraday absolute returns and a return-per-notional illiquidity proxy. Volume is not order-book depth. Per-minute log returns reset at each UTC session; session boundaries contribute a zero return, so no overnight return is included. Realized volatility is sqrt(sum(log returns in bps squared)), unannualised and sample-window-dependent. The return standard deviation is descriptive, not a forecast.

## Uncertainty

Each policy has 32 independent generated fill-noise paths conditional on the same fixed market path and assumptions. Report mean, standard deviation and empirical p05/p95. This captures only the configured noise mechanism, not price-path uncertainty or model uncertainty.

The API paired bootstrap uses whole non-overlapping windows. The supplied evaluation scripts first average configuration differences within each session, then resample paired sessions. Negative policy-minus-TWAP differences indicate lower simulated cost. Two or three sessions are inadequate for robust inference. No multiple-hypothesis-adjusted selection or realised performance claim is made.

## Reproducibility and lineage

Dataset CSV/raw/quarantine checksums are verified before loading. The experiment ID hashes dataset checksums, validated configuration, engine version and Python engine-source hash. SQLite INSERT OR IGNORE makes duplicate runs idempotent. This is useful evidence tracking, not tamper-proof storage: a filesystem owner can modify both data and manifest. Source artifacts and provenance accompany exports; no secret signing key or independent audit authority is claimed.
