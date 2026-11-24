# MarketLens interview and study guide

## Explain it in 45 seconds

MarketLens compares execution policies on the same market tape. It validates trade and optional quote data, builds minute-level liquidity and volatility analytics, then compares TWAP, historical-profile VWAP and lagged-volume participation. I made fill capacity, spread, fees and temporary impact explicit. It measures implementation shortfall including the cost of unfinished orders, saves reproducible runs in SQLite, and exposes a FastAPI dashboard and evidence exports. The historical sample is trade-only, so its spreads and fills remain assumptions rather than observations.

Personalise this explanation to your own contribution. Study the code and reproduce a run before presenting it as work you understand.

## Terms with one example

- **Bid / ask:** someone offers to buy at 99.99 and someone offers to sell at 100.01. Midpoint is 100; spread is 0.02, or 2 bps.
- **Basis point:** one ten-thousandth. A 5 bps price difference on 100 is 0.05.
- **Parent order:** the total quantity an investor wants to buy or sell.
- **Child order / fill:** the smaller amount executed during one interval. In this project fills are simulated.
- **TWAP:** spread the cumulative quantity target equally over time.
- **VWAP:** volume-weighted average price. A VWAP *schedule* uses an expected volume profile; realised market VWAP is a separate benchmark calculated afterward.
- **POV:** participation of volume. This implementation uses preceding-minute volume to avoid seeing current-minute outcomes before deciding.
- **Slippage:** signed price difference from a benchmark. The benchmark and fee treatment must be stated.
- **Implementation shortfall:** total signed cost versus doing the full parent order at arrival, including fees and the terminal mark on unfilled quantity.

## Walk the code

1. `data.py:read_csv` parses timezone-aware rows, validates numeric fields, rejects duplicate identifiers into quarantine and enforces a single symbol.
2. `data.py:register` writes raw/clean data and checksums using a staging directory and atomic install.
3. `analytics.py:bars` aggregates trades into UTC minute intervals and backward-matches quotes at interval starts.
4. `analytics.py:volume_profile` fits mean volume by UTC minute strictly before the cutoff.
5. `engine.py:prepare` validates execution times, date/window coverage and profile availability.
6. `engine.py:simulate` chooses a policy request, enforces fill capacity and computes costs.
7. `engine.py:compare` evaluates all policies on matched data/noise and creates a content-derived experiment ID.
8. `store.py` persists immutable results with SQLite transactions and uniqueness.
9. `app.py` exposes typed APIs, import validation, comparisons, history, diagnostics and exports.
10. `static/app.js` fetches evidence, renders SVG charts and restores saved results.

## Twenty questions to practise

1. **Why is future volume leakage a problem?** A schedule built using realised execution-day volume has hindsight. Our profile uses earlier sessions only; POV uses a lag.
2. **Can the simulator use current volume?** Yes as an ex-post limit on fills. The policy cannot use it when setting the request. Decision and outcome models have different information sets.
3. **Why not execute everything at market VWAP?** VWAP is a benchmark known after the window, not a guaranteed obtainable fill price.
4. **What does the square-root impact term prove?** Nothing causal. It is a configurable scenario assumption; the historical tape never reacts to the simulated order.
5. **How do you price trades without quotes?** A labelled retrospective minute-VWAP proxy plus assumed spread, impact and noise. This is weaker than quote/order-book replay.
6. **What if no quote is fresh?** The engine falls back to the proxy and preserves the reference label per fill.
7. **Why not use the next quote?** That quote was unavailable at decision time. Backward as-of matching avoids future quote information.
8. **How is sell cost signed?** A sale below arrival is adverse positive cost. Fees stay positive. Multiply price differences by side sign.
9. **Why include opportunity cost?** Otherwise a policy that avoids difficult fills can look cheap while leaving most of the order unfinished.
10. **Why not force a final fill?** That invents liquidity and violates the cap. We report remaining quantity and its terminal mark.
11. **Are the noise intervals confidence intervals for future costs?** No. They condition on the observed path and assumed noise distribution. Price-path and impact-model uncertainty are not captured.
12. **How do you compare policies statistically?** Paired differences on matched windows. The study resamples whole sessions, averaging same-session configurations first. With only two real evaluation sessions the intervals are descriptive and fragile.
13. **Why no profitable-strategy claim?** Execution quality is not an alpha strategy, and these fills are hypothetical. None of these calculations establishes executable profit.
14. **What is the strongest numerical test?** The cost decomposition reconciles to total shortfall; buy/sell signs, zero-volume cases and capacity invariants also have independent expected outcomes.
15. **How is reproducibility handled?** Source checksums, source-code fingerprint, full config, risk-path count and seed determine the ID. Results are saved rather than silently recalculated on read.
16. **Is hashing tamper-proof?** No. A filesystem owner could rewrite both files and checksums. Independent signing or external audit storage would be a different system.
17. **What happens with concurrent identical requests?** SQLite uniqueness and INSERT OR IGNORE retain one result. Connections and transactions are scoped to each operation.
18. **Why use a simple frontend?** It keeps this research package easy to run without a Node build chain while still exercising APIs and interactive charts.
19. **What would production require?** Authentication, authorization, async jobs, resource quotas, transport-level limits, secure deployment and richer data/observability. The current app is local only.
20. **How does this relate to HSBC?** It demonstrates market-data engineering, quantitative experimentation, trading/execution analytics and dependable research software. It is not a representation of HSBC's internal execution stack.

## Exercises

- Calculate by hand a buy order of 100 units: 60 fill at 101, arrival 100, terminal 102, fees 1. Total shortfall = 60 + 80 + 1 = 141 cash, or 141 bps on 10,000 initial notional.
- Repeat for a sell order and explain the sign changes.
- Set noise, impact, fees and spread to zero on a flat tape. Explain why cost is zero for both sides.
- Increase order size until the capacity cap binds. Explain why completion changes and why filled VWAP alone can mislead.
- Move the profile cutoff into the future. Confirm the API rejects it.
- Modify future trade volume while holding prior training data fixed. Confirm the schedule weights do not change.
- Inspect a trade-only historical run and find `reference_kind=bar_vwap_proxy` and `spread_kind=assumed`.
- Compare the fingerprints of two runs after changing one configuration field.
