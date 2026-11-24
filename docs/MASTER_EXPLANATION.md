# MarketLens: the master explanation

Everything you need to own this project in an interview: what it does, the finance behind it, how each line of the engine works, what the results actually say, what I verified by running it, and where it is weak.

---

## 0. The 30-second pitch

> "MarketLens is a research workbench for **execution analytics**. If a fund wants to buy a large quantity of something, *how* it slices that order over time changes what it pays. I built a pipeline that ingests trade (and optionally quote) data, validates and quarantines bad records, and turns it into minute bars with liquidity, volatility and intraday-pattern analytics. On top of that, a simulator replays three execution policies — **TWAP**, a **historical-profile VWAP**, and **participation-of-volume (POV)** — against the *same* market tape and the *same* cost assumptions, and measures **implementation shortfall** including the cost of anything left unfilled. Every run is content-hashed so it's reproducible, saved to SQLite, and exposed through a FastAPI service and a dashboard that labels what was observed versus what was simulated."

What it is **not**: a trading system, a live order router, an order-book simulator, or proof that any policy saves money.

---

## 1. Verification (24 Nov 2026; after the fixes in §9)

| Check | Result |
|---|---|
| `pip install -r requirements.txt` in a clean venv; `run.ps1` launcher | ✅ OK, serves the app |
| `python -m unittest discover -s tests` | ✅ **42/42 pass** on Windows (Py 3.13.5) **and** Linux (Py 3.12, in Docker) |
| `scripts/evaluate.py` (synthetic study) | ✅ 12 configs × 3 policies = 36 evaluations |
| `scripts/evaluate_historical.py` (BATUSDT) | ✅ 8 configs × 3 = 24 evaluations |
| Cross-platform reproducibility | ✅ Windows and Linux give **identical** dataset ID, code hash, experiment IDs and metrics |
| Cost decomposition reconciles | ✅ max error 1.8e-10 (synthetic), 6.8e-13 (historical) |
| Live server, all API routes | ✅ health, datasets, analytics, quarantine, experiments, replay idempotence, JSON/CSV export, batches, `/docs` |
| Leakage guard (cutoff after start) / unknown fields | ✅ Both rejected with 422 |
| Browser acceptance (`scripts/browser_check.py`) | ✅ **9/9 pass**, including mobile layout and no JS errors |
| Docker build + run | ✅ Builds, serves, runs experiments; CI workflow steps pass inside it |
| Remote GitHub Actions, macOS | ❌ Not run (no hosted repo / no Mac) |

---

## 2. Do the resume bullets match the code?

**Bullet 1:** *"Engineered market-data pipelines to analyse liquidity, volatility and intraday patterns; compared TWAP, VWAP and participation-based execution under explicit fill, fee and slippage assumptions."*

| Claim | Evidence | Verdict |
|---|---|---|
| Market-data pipelines | CSV ingestion + validation + quarantine ([data.py](../marketlens/data.py)), Binance archive importer with SHA256 verification ([import_binance.py](../scripts/import_binance.py)), minute-bar builder ([analytics.py](../marketlens/analytics.py)) | ✅ Accurate |
| Liquidity | Traded volume, notional, trade count, quoted spread (when quotes exist), Amihud-style illiquidity proxy | ✅ Accurate. Note: on the real data, spread is *assumed*, not measured |
| Volatility | Per-minute log returns, realised vol √Σr², return std | ✅ Accurate |
| Intraday patterns | Mean volume / mean |return| / mean spread by UTC minute-of-day | ✅ Accurate |
| TWAP, VWAP, participation | `engine.simulate` — all three | ✅ Accurate |
| Explicit fill, fee, slippage assumptions | Capacity cap, fee bps, half-spread, √-impact, seeded noise, all in `Config` and printed in every result | ✅ Accurate |

**Bullet 2:** *"Evaluated implementation shortfall and execution risk across matched trading scenarios; delivered reproducible experiments, FastAPI services and an interactive dashboard separating observed data from simulated fills."*

| Claim | Evidence | Verdict |
|---|---|---|
| Implementation shortfall | Full signed IS with fees + opportunity cost + 6-way decomposition | ✅ Accurate, and done properly |
| Execution risk | 32 fill-noise paths → mean/std/p05/p95 of IS | ⚠️ **True but thin.** It's noise sensitivity on one fixed price path, with σ = 0.5 bps the bands are ~0.15 bps wide. It is *not* timing/price risk. Be ready to say exactly that |
| Matched trading scenarios | Same tape, same noise path, same costs for all 3 policies; 2 sides × 2 sizes × N sessions | ✅ Accurate |
| Reproducible experiments | Content-hashed IDs, code fingerprint, dataset checksums, SQLite ledger | ✅ Accurate; identical IDs on Windows and Linux (after the fix in §9) |
| FastAPI services | One FastAPI app, 10 routes, typed Pydantic schemas, OpenAPI docs | ✅ ("services" plural is normal phrasing) |
| Interactive dashboard separating observed from simulated | Each fill tagged `reference_kind` (`quote_mid` / `bar_vwap_proxy`) and `spread_kind` (`observed_quote` / `assumed`); banner and labels throughout | ✅ Accurate |

**Overall: both bullets are supported by working code.** The two things to be careful saying in an interview: (1) "execution risk" here means fill-noise sensitivity, and (2) the real-data study is tiny (2 evaluation sessions, ~$127–$630 orders in a small crypto token).

---

## 3. Finance foundations (from zero)

### 3.1 The problem: executing a large order
A portfolio manager decides to **buy 1,000,000 shares**. That's the **parent order**. Sending it all at once would eat through the order book and push the price up against you (**market impact**). So a trader/algorithm splits it into **child orders** over time. The question is *how*.

Two forces conflict:
- **Trade fast** → more impact (you're a bigger fraction of the market), but less exposure to the price drifting away (**timing risk**).
- **Trade slow** → less impact, but more timing risk and a chance you don't finish (**opportunity cost**).

This is the classic **Almgren–Chriss** trade-off (2000). MarketLens doesn't optimise it; it *measures* where three standard policies land on it.

### 3.2 Vocabulary
- **Bid / ask**: best price someone will buy at / sell at. **Mid** = (bid+ask)/2. **Spread** = ask − bid.
- **Basis point (bp)**: 1/10,000 = 0.01%. A 2 bp spread on 100 is 0.02.
- **Crossing the spread**: a buyer who wants to fill now pays the ask = mid + half-spread. So **half-spread is the minimum cost of immediacy**.
- **Slippage**: signed difference between your average fill price and a benchmark price.
- **Arrival price**: the price when the order was handed to the trader (decision price). Benchmark for IS.
- **Market VWAP**: Σ(price × volume) / Σ volume over the window. Benchmark for "VWAP slippage". It's only known **after** the window ends.

### 3.3 The three policies
| Policy | Rule | Intuition | Weakness |
|---|---|---|---|
| **TWAP** (time-weighted) | Trade Q/N each minute | Simple, predictable | Ignores when liquidity is available (e.g. U-shaped intraday volume) |
| **VWAP** (volume-weighted schedule) | Trade in proportion to *expected* volume per minute, from a historical profile | Trade more when the market is busy → lower participation → lower impact; tracks market VWAP | Profile is a forecast; today may differ |
| **POV** (participation of volume) | Each minute trade p% of *observed* market volume | Adapts to real liquidity | Completion time is unknown; may finish very early or never |

Key subtlety that MarketLens gets right: **VWAP the schedule ≠ VWAP the benchmark.** Using today's actual volume to schedule today is hindsight (look-ahead bias). The profile here is built from **earlier sessions only**.

### 3.4 Implementation shortfall (Perold, 1988)
IS = the difference between the "paper portfolio" (you magically bought everything at arrival price, free) and what actually happened.

With side s = +1 buy / −1 sell, arrival A, quantity Q, fills (qᵢ, pᵢ), filled F, unfilled U = Q − F, final price T:

```
Execution cost   = s × Σ qᵢ (pᵢ − A)          # paid vs arrival on what you filled
Fees             = Σ qᵢ pᵢ × fee_bps/10,000    # always ≥ 0
Opportunity cost = s × U × (T − A)             # what the unfilled part "cost" you
IS               = Execution + Fees + Opportunity
IS (bps)         = 10,000 × IS / (Q × A)
```

Positive = bad (cost) for both sides. Negative = the market moved in your favour.

**Why opportunity cost matters:** without it, a policy that only fills the easy 30% looks cheap. With it, the 70% you never bought is marked to the final price — if price rose, that's a real loss.

**Hand example (buy):** Q = 100, arrival 100, 60 filled at 101, terminal 102, fees 1.
Execution = 60 × (101 − 100) = 60. Opportunity = 40 × (102 − 100) = 80. IS = 60 + 1 + 80 = **141**, on notional 10,000 → **141 bps**.
For a **sell** with fills at 99 and terminal 98: execution = −1 × 60 × (99 − 100) = 60; opportunity = −1 × 40 × (98 − 100) = 80 → same 141 bps. Falling price hurts a seller.

### 3.5 Market impact: the square-root law
Empirically (Torre/Barra, Almgren et al., Tóth et al.), impact grows roughly with the **square root** of participation:

```
impact_bps = k × sqrt(q / V)
```
q = your quantity in the minute, V = market volume in the minute, k = coefficient (default 5 bps). Trading 4% of volume → 5 × 0.2 = 1 bp. Trading 16% → 2 bps. Doubling your rate doesn't double cost per share — but it does double the shares paying it.

In MarketLens this is **temporary** impact only: it changes *your* fill price but the historical tape doesn't react. No **permanent** impact (your buying doesn't move later prices). This is the single biggest simplification.

### 3.6 Liquidity and volatility metrics used
- **Traded volume / notional / trade count** per minute — liquidity *proxy* (it's not order-book depth).
- **Quoted spread (bps)** = 10,000 × (ask − bid)/mid.
- **Amihud illiquidity** ≈ mean(|return| / notional): how much price moves per unit of money traded. Higher = less liquid. (Synthetic 0.0014 vs BATUSDT 0.028 — BAT is much less liquid per dollar.)
- **Log return** rₜ = ln(Pₜ / Pₜ₋₁), in bps; reset to 0 at each session start so there's no overnight jump.
- **Realised volatility** = √Σ rₜ² (unannualised, depends on window length).

---

## 4. Architecture

```
CSV / Binance ZIP ──► validate + quarantine ──► content-addressed dataset folder (immutable, checksummed)
                                                   │
                                                   ▼
                          minute bars + quotes as-of join + analytics (analytics.py)
                                                   │
                         prior-session volume profile (cut-off enforced)
                                                   │
                                                   ▼
               matched simulator: TWAP / VWAP / POV on same tape + same noise (engine.py)
                                                   │
                                                   ▼
                     content-hashed experiment ──► SQLite ledger (store.py, WAL, INSERT OR IGNORE)
                                                   │
                                                   ▼
                    FastAPI (app.py) ──► JSON/CSV exports ──► vanilla JS + SVG dashboard (static/)
```

Design principle: **the numerical engine knows nothing about HTTP or the browser.** You can call `compare()` from a script (the evaluation scripts do exactly that).

| File | Lines | Responsibility |
|---|---|---|
| [models.py](../marketlens/models.py) | 37 | Pydantic schemas: `Config`, `ImportRequest`, `BatchRequest`. Rejects unknown fields, NaN/Inf, bad ranges, POV > cap |
| [data.py](../marketlens/data.py) | 142 | Parse/validate CSV, quarantine, content-addressed registry, integrity check on load, synthetic generator |
| [analytics.py](../marketlens/analytics.py) | 70 | Minute bars, quote as-of join, returns, summary stats, volume profile |
| [engine.py](../marketlens/engine.py) | 151 | `prepare` (window/leakage checks), `simulate` (one policy), `compare` (all three + risk), `paired_bootstrap` |
| [store.py](../marketlens/store.py) | 32 | SQLite persistence, idempotent saves |
| [app.py](../marketlens/app.py) | 123 | FastAPI routes, middleware (timing, security headers, body-size limit), error mapping |
| [static/](../marketlens/static/) | ~45 | Dashboard; hand-rolled SVG charts; no build step, no CDN |

---

## 5. Code walkthrough, stage by stage

### 5.1 Ingestion — [data.py:18 `read_csv`](../marketlens/data.py#L18)
- Requires columns (`timestamp, symbol, trade_id, price, quantity` or `timestamp, symbol, bid, ask`).
- Each row: timestamp **must be timezone-aware** (naive timestamps are ambiguous → rejected), converted to UTC. Price/qty finite and > 0. Quotes: not crossed (ask ≥ bid). Duplicate trade IDs / quote timestamps rejected.
- Bad rows don't kill the import — they go to **quarantine** with line number and reason. If *every* row is bad, or there are mixed symbols, the whole import fails.
- Stable sort by timestamp (out-of-order rows are fixed, ties keep original order).
- Max 100,000 rows per file (bounded memory).

### 5.2 Registration — [data.py:62 `register`](../marketlens/data.py#L62)
- **Content addressing:** dataset ID = first 16 hex of SHA256(name, raw text, source, description). Same input → same ID → registering twice is a no-op (idempotent).
- **Atomic install:** writes into a temp `.import-xxxx` directory, then `rename` to the final ID. Rename is atomic on the same filesystem, so a reader never sees a half-written dataset. If two processes race, the loser sees the folder exists and moves on.
- Saves cleaned CSV, **raw original**, quarantine JSON, and a manifest with SHA256 of every file.
- [data.py:106 `load`](../marketlens/data.py#L106) re-hashes every file before using it → tampering/corruption detected.

### 5.3 Synthetic demo — [data.py:119 `demo`](../marketlens/data.py#L119)
Seed 20261124, 6 sessions × 120 minutes (09:30–11:30 UTC), symbol `DEMO`, start price 100:
- Price: geometric random walk, σ = 5 bps/min, **2.5× vol in minutes 45–70** (a stress regime), drift +1.5 bps/min on even days, −1 bp on odd days.
- Volume: lognormal, **1.8× in first 20 and last ~25 minutes, 0.7× in the middle** → a U-shaped intraday profile (realistic; real markets are busiest at open/close). This is what makes VWAP differ from TWAP.
- Spread: 1 bp normally, **3 bp in the stress window**.
- 3 trades per minute, 1 quote per minute.
- Two deliberately bad rows (a duplicate trade, a negative price) to prove quarantine works.

### 5.4 Real data — [import_binance.py](../scripts/import_binance.py)
- Downloads Binance public **aggTrades** daily ZIPs for BATUSDT (Basic Attention Token vs USDT), 8–11 Jan 2024, and their `.CHECKSUM` files; refuses to proceed on SHA256 mismatch.
- Handles both millisecond and microsecond timestamps (Binance switched in 2025) with integer arithmetic (no float precision loss).
- Keeps only 09:00–12:00 UTC → 8,809 trades. **No quotes** — so all real-data spreads are assumed.

### 5.5 Minute bars — [analytics.py:6 `bars`](../marketlens/analytics.py#L6)
- Floors each trade to its minute; aggregates volume, notional, count, first/last/high/low.
- **Fills empty minutes within a session only** (volume 0, price carried forward) — never creates fake overnight minutes.
- Bar VWAP = notional/volume.
- **Quote as-of join**: `pd.merge_asof(direction='backward', tolerance=max_age)` — for each minute start, take the most recent quote **at or before** that moment, and only if it's ≤ 120s old. Using the *next* quote would be look-ahead.
- Returns reset per session.

### 5.6 Volume profile — [analytics.py:57 `volume_profile`](../marketlens/analytics.py#L57)
Mean volume per `HH:MM` across all bars **strictly before `training_end`**. That's the VWAP forecast.

### 5.7 Preparation & leakage guards — [engine.py:21 `prepare`](../marketlens/engine.py#L21)
Rejects (HTTP 422) if:
- `training_end > start` (profile would see the future),
- start/end not on minute boundaries, window > 6 hours, or crosses UTC days,
- any minute in the window missing from the data,
- window has zero volume,
- **any execution minute missing from the training profile** — it refuses rather than quietly using today's volume.

Weights for the window are renormalised to sum to 1. It also grabs the volume of the minute just before `start` (if adjacent) for POV's first decision.

### 5.8 The simulator — [engine.py:51 `simulate`](../marketlens/engine.py#L51)
For each minute i:

```
filled_so_far = Q − remaining
TWAP/VWAP:  target_cum[i] = Q × cumsum(weights)[i]    (TWAP weights = 1/N)
            request = max(0, target_cum[i] − filled_so_far)    # catches up if behind
POV:        request = p × previous_minute_volume              # LAGGED — no peeking
capacity  = max_participation × this_minute_volume            # simulator-side limit
q         = min(remaining, request, capacity)
```
Note the **information-set separation**: the *policy* decides using only past information; the *simulator* is allowed to use current-minute volume to decide how much could realistically fill. That's the correct way to avoid look-ahead while still being realistic about capacity.

**Pricing each child fill:**
```
base   = quote mid at minute start            (if a fresh quote exists)
       = minute bar VWAP                       (otherwise — labelled "bar_vwap_proxy")
spread = observed quote spread  OR  assumed_spread_bps (default 2)
impact = impact_bps × sqrt(q / V)              (default k = 5)
noise  = Normal(0, noise_bps)                  (default σ = 0.5, seeded)
price  = base × (1 + s × (spread/2 + impact + noise)/10,000)
fee    = q × price × fee_bps/10,000            (default 1 bp)
```

**Cost decomposition** (accumulated per minute, cash units):
```
timing  = s × q × (base − arrival)     # the market moved before you traded
spread  = q × base × (spread/2)/10,000
impact  = q × base × impact/10,000
noise   = q × base × noise/10,000
fees, opportunity (as in §3.4)
```
Because `price − arrival = (base − arrival) + base × (half-spread + impact + noise)/10,000`, these **add up exactly** to IS. The code computes `decomposition_error = IS − Σ components` as a self-check (≈1e-10 in practice — floating-point only).

**Never force-fills**: if capacity runs out, the remainder stays unfilled and is charged opportunity cost.

Outputs per policy: completion %, IS (cash & bps), execution VWAP, market VWAP, VWAP slippage, arrival slippage, every component, plus a per-minute fill ledger (requested, filled, price, participation, reference kind, spread kind, cumulative, remaining).

### 5.9 Matched comparison & risk — [engine.py:114 `compare`](../marketlens/engine.py#L114)
- Runs all three policies on the **same frame, profile, and noise path** — a *paired* experiment, so differences are due to the policy, not luck.
- **Execution risk:** draws 32 noise paths (seeded), reruns each policy on each, reports mean/std/p05/p95 of IS bps. Labelled honestly: *"conditional fill-noise sensitivity on this fixed market path; not market VaR."*
- **Experiment ID** = SHA256(dataset file hashes, full config, SHA256 of all engine source files, engine version, path count)[:24]. Change one parameter or one line of code → new ID. Same everything → same ID.

### 5.10 Statistics — [engine.py:143 `paired_bootstrap`](../marketlens/engine.py#L143)
Given per-window differences (VWAP − TWAP, POV − TWAP), resample windows with replacement 2,000 times, report mean and 2.5/97.5 percentiles. The evaluation scripts first **average all configs within a session** so one session counts once (avoids **pseudo-replication** — treating 4 correlated configs on one day as 4 independent observations).

### 5.11 Persistence — [store.py](../marketlens/store.py)
- SQLite in **WAL mode** (readers don't block the writer).
- One connection per operation, inside a transaction.
- `INSERT OR IGNORE` on a primary key = content ID → **concurrent identical requests store exactly one row** (there's a test for this).
- Results are stored, not recomputed on read: opening an old experiment shows what the old code produced.

### 5.12 API — [app.py](../marketlens/app.py)
| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Version, request count |
| GET/POST | `/api/datasets` | List / import CSV |
| GET | `/api/datasets/{id}/analytics` | Bars + summary |
| GET | `/api/datasets/{id}/quarantine` | Rejected rows with reasons |
| POST | `/api/experiments` | Run the 3-policy comparison |
| GET | `/api/experiments`, `/{id}`, `/{id}/export.json`, `/{id}/fills.csv` | History, detail, exports |
| POST | `/api/batches` | 2–12 non-overlapping windows + paired bootstrap |

Middleware: `X-Process-Time` header, access logging, `nosniff`, `no-referrer`, strict **Content-Security-Policy** (no external/inline scripts, no framing), POST body ≤ 13 MB via Content-Length. Exception handlers map `ValueError`→422, `KeyError`/`FileNotFoundError`→404. Dataset IDs are regex-validated (blocks path traversal like `../../`).

### 5.13 Frontend — [static/app.js](../marketlens/static/app.js)
Vanilla JS, no framework. Charts are SVG strings built **only from numbers**; all user-supplied text (dataset names, descriptions) goes through `textContent`, never `innerHTML` → no XSS. Four views: Workbench, Experiments (restore saved runs), Data registry (import + quarantine), Methodology.

### 5.14 Tests — [tests/test_marketlens.py](../tests/test_marketlens.py) (42 tests)
- **Numerical invariants:** flat tape + zero costs → zero IS; uniform profile ⇒ VWAP == TWAP; buy/sell sign symmetry; capacity never exceeded / never overfill; zero-volume minute → zero fill; opportunity-cost sign; decomposition reconciles; same seed → same result.
- **Leakage:** cutoff after start rejected; **changing future volume doesn't change the schedule**; POV uses lagged volume; quotes are backward-only and respect staleness.
- **Data integrity:** naive timestamps, missing columns, NaN/negative/duplicate rows, crossed quotes, checksum tamper detection, ms/µs timestamps, no invented spread for trade-only data, platform-independent dataset ID and byte-exact raw storage.
- **API/infra:** validation errors, unknown IDs, idempotent create + exports, batch overlap rejection, path traversal, concurrent duplicate requests (store and HTTP).

---

## 6. What the results actually say

### 6.1 Synthetic study (3 training days → 3 evaluation days, 09:30–11:30)
Configs: buy/sell × 500/2,500 units × 3 days. Price ≈ 100, so 500 units ≈ 50k notional.

Selected rows (IS in bps):

| Day | Side | Qty | TWAP | VWAP | POV | Completion T/V/P |
|---|---|---|---|---|---|---|
| 09 Jan | buy | 500 | −37.8 | −41.9 | −18.1 | 100/100/100 |
| 09 Jan | buy | 2,500 | −90.1 | −89.1 | −120.6 | 58/59/28 |
| 10 Jan | buy | 500 | 166.5 | 167.4 | 122.3 | 100/100/100 |
| 10 Jan | sell | 500 | −160.1 | −161.2 | −115.6 | 100/100/100 |

**How to read it:**
1. **Timing/drift dominates.** On 10 Jan price rose strongly, so every buy costs ~120–170 bps and every sell "earns" a similar amount. That's market movement, not algorithm skill.
2. **Size 2,500 hits the capacity cap.** Average minute volume is ~59 units; cap 20% → ~12/min × 120 ≈ 1,420 max → TWAP/VWAP only ~55–58% complete, POV (10%) ~27%. The rest becomes **opportunity cost**, which is huge here (e.g. −2,731 cash for POV on 9 Jan — negative because price *fell* for that buyer, so not finishing was lucky).
3. **The evaluation scripts average buy and sell within a session**, which **cancels directional drift** (timing and opportunity flip sign with side) and leaves mostly the *cost* components. Result: VWAP − TWAP = **−0.07 bps**, POV − TWAP = **−0.55 bps**. Tiny. POV looks slightly cheaper mostly because it fills *less* (fewer shares paying spread/impact/fees) on the large orders.

### 6.2 Historical study (BATUSDT, train 8–9 Jan → evaluate 10–11 Jan 2024)
BAT price ≈ 0.25 USDT, so **500 BAT ≈ $127** and 2,500 ≈ $633. Average minute volume ≈ 7,500 BAT.

| Day | Side | Qty | TWAP | VWAP | POV |
|---|---|---|---|---|---|
| 10 Jan | buy | 500 | 29.9 | 34.8 | 5.2 |
| 11 Jan | buy | 500 | 24.2 | 22.8 | −2.4 |
| 11 Jan | sell | 2,500 | −19.7 | −18.1 | 26.6 |

All orders 100% complete. Paired-session result (buy/sell averaged): VWAP − TWAP = **+0.05 bps**, POV − TWAP = **+0.84 bps** (POV slightly *worse*).

**Critical insight I found by running it:** on this data **POV finishes the entire order in the first 2 minutes** (10% of ~7,500 BAT ≫ 500 BAT), while TWAP/VWAP spread it over 120 minutes. So the big per-row POV differences (e.g. 24 vs −2 bps) are just "buy at 09:30 vs. buy across the morning" — pure price drift. Once drift is cancelled by averaging sides, POV is ~0.8 bp *worse*, because concentrating the order into 2 minutes means higher participation → higher √-impact.

**Worked real example (buy 500 BAT, 11 Jan, TWAP):** arrival 0.2531 (first trade; no quotes) → notional 126.55. TWAP trades 4.17 BAT/min. Execution VWAP 0.253688. Components: timing 0.28 (≈22 bps — price drifted up), half-spread 0.0127 (1 bp, *assumed*), fees 0.0127 (1 bp), impact ≈0.003 (participation ~0.1%). Total ≈ 0.307 → **24.2 bps**. The "cost" of executing is ~2.2 bps; the other ~22 bps is the market moving.

**The honest one-line conclusion:** *after cancelling drift, all three policies cost ~2–3 bps, almost entirely the assumed half-spread plus fee; the differences between policies are sub-1 bp and driven by the assumed impact model. Nothing here establishes that one policy is better.* That's a strong, mature answer in an interview — it shows you understand what your simulator can and can't tell you.

### 6.3 Why the bootstrap CIs mean little
With 2 or 3 sessions, resampling has only a handful of possible means; the "95% CI" is roughly [min, max] of the session values. The code and reports say so explicitly. A real study needs dozens to hundreds of sessions.

---

## 7. Engineering decisions worth talking about

1. **Separate decision information from outcome information** (policy uses lagged/prior data; simulator uses current volume for capacity). The core anti-look-ahead idea.
2. **Content addressing + code fingerprint** for reproducibility: identical inputs → identical IDs → idempotent storage; any change → new ID.
3. **Quarantine, don't drop silently.** Bad rows are kept with reasons; raw files are kept.
4. **Atomic dataset install** via temp dir + rename.
5. **Self-checking accounting** (`decomposition_error`).
6. **Honest labelling** per fill (`bar_vwap_proxy`, `assumed`) instead of pretending trade-only data has spreads.
7. **No framework frontend** — zero build tooling, strict CSP, textContent for user data.
8. **Bounded work** (≤ 6h window, ≤ 12 batch windows, ≤ 100k rows, ≤ 13 MB POST) because requests are synchronous.

---

## 8. Limitations (say these before the interviewer does)

- **Minute-bar replay, not order-book simulation.** No queue position, latency, partial fills at levels, cancellations.
- **No permanent impact; the tape never reacts** to your orders. Temporary √-impact coefficient is assumed, not calibrated.
- **Trade-only real data:** spreads assumed (2 bps), fill reference = minute VWAP which is *retrospective* (includes trades after minute start — mild look-ahead in the price proxy, documented).
- **Arrival price** on trade-only data = first trade of the first minute, not a mid.
- **"Execution risk" = fill-noise sensitivity only**, not price-path or model risk.
- **Tiny sample:** 2 real evaluation sessions, 1 illiquid crypto token, small orders where impact is negligible.
- **POV has no end-time awareness** (it can finish in minute 2 or never) — real POV algos have min/max participation bands and completion deadlines.
- **No scheduling optimisation** (e.g. Almgren–Chriss risk-aversion trade-off), no adaptive VWAP, no limit orders.
- **Single-user, unauthenticated, synchronous**; Docker and CI provided but not verified.

---

## 9. Bugs found and fixed

1. **Windows line endings broke reproducibility (fixed).** `pd.DataFrame.to_csv()` returns `\r\n` on Windows, so the synthetic demo text hashed differently → dataset ID `2cdcc781…` instead of `22a2df81…` → different experiment IDs and a duplicate "Synthetic demo" in the registry. `write_text` then translated newlines again, producing `\r\r\n` in raw files. **Fix:** explicit `lineterminator='\n'` ([data.py:78-80](../marketlens/data.py#L78-L80), [data.py:141-142](../marketlens/data.py#L141-L142)) and `write_text(..., newline='')` for stored files. **Tests added:** `test_demo_identity_is_platform_independent` (pins the ID, asserts no `\r` in stored files) and `test_raw_files_stored_byte_for_byte`. Windows and Linux now produce identical experiment IDs.
   *Interview story:* "My reproducibility guarantee was silently OS-dependent. Content hashing is only as good as byte-level determinism, so I pinned line endings and added a regression test that fixes the expected ID."
2. **Browser harness couldn't run (fixed).** Playwright evaluates string predicates via `eval`, which the app's own CSP (`script-src 'self'`) correctly blocks. **Fix:** the *test* browser uses `bypass_csp=True` ([browser_check.py](../scripts/browser_check.py)); the app's security policy is unchanged.
3. **Mobile layout overflowed (fixed).** At 390px the page was 486px wide, because `1fr` grid tracks can't shrink below their content's minimum width. **Fix:** `minmax(0,1fr)` tracks, `min-width:0` on grid children, and metrics stack to one column under 520px ([style.css](../marketlens/static/style.css)). Verified: 390px viewport → 390px page, before and after running a comparison; desktop unchanged.
4. **Not changed (by design):** the headline noise path equals risk path #0 (same seed). Importing `marketlens.app` creates the demo dataset as a side effect (module-level `app = create_app()`); with fix 1 this is now idempotent on every OS.

Because `data.py` changed, the engine's code fingerprint changed, so the reports were regenerated: **new experiment IDs, numerically identical metrics and bootstrap results.**

---

## 10. Hard interview questions and strong answers

**Q: Why is your VWAP not just executing at market VWAP?**
Market VWAP is only known after the window closes. A VWAP *strategy* has to forecast the volume curve; I use the mean minute-of-day volume from prior sessions only, with a cut-off the API enforces.

**Q: How do you prevent look-ahead bias?**
Three places: the volume profile uses only data before `training_end` (and refuses if a minute is missing rather than borrowing today's); POV uses the *previous* minute's volume; quotes are matched backward-as-of with a staleness limit. There's a test that perturbs future volume and asserts the schedule is unchanged. One residual: on trade-only data the fill reference is the minute's VWAP, which is retrospective — it's labelled as a proxy.

**Q: Why include opportunity cost?**
Otherwise not trading looks free. A policy that fills 28% at a good price would beat one that fills 100% at a slightly worse price, which is nonsense from the PM's perspective.

**Q: Your POV beat TWAP by 26 bps on 11 Jan. Is POV better?**
No. On BATUSDT, 10% of minute volume is far larger than the order, so POV finished in 2 minutes. That difference is just the price drift between 09:30 and the rest of the morning. When I average buy and sell to cancel drift, POV is ~0.8 bp *worse* due to higher instantaneous participation.

**Q: Why square-root impact?**
It's the empirical stylised fact across markets (cost ∝ σ·√(Q/V)). Here it's an assumption with a configurable coefficient, not something I estimated — the historical tape can't tell you your own impact since your orders were never there.

**Q: What does your "execution risk" measure?**
Dispersion of IS across 32 seeded fill-noise paths on a fixed price path. It isolates execution-noise sensitivity; it doesn't capture timing risk (price-path uncertainty), which is the dominant risk in reality. To capture that I'd bootstrap or simulate price paths, or evaluate across many sessions.

**Q: How would you make this production-grade / closer to a bank's TCA?**
Tick-level quotes and depth (L2/L3), a queue/fill model calibrated on actual child-order fills, permanent + temporary impact calibrated per instrument, arrival = decision-time mid, benchmark set (arrival, interval VWAP, close, PWP), many hundreds of orders with regression on size/volatility/spread (pre-trade cost model), an Almgren–Chriss optimiser for schedule choice, async workers, auth, Postgres.

**Q: How is reproducibility guaranteed?**
Experiment ID = hash of dataset checksums + full config + engine source hash + version. Datasets are immutable and re-verified on load. SQLite `INSERT OR IGNORE` makes reruns idempotent, even concurrently. I found and fixed a subtle case: Windows CRLF output made the synthetic dataset hash OS-dependent. Line endings are now pinned, a regression test fixes the expected ID, and Windows and Linux produce identical experiment IDs.

**Q: What did the decomposition check catch?**
It guards the accounting: IS must equal timing + spread + impact + noise + fees + opportunity. Any sign error or double-count shows up as a non-zero residual. In recorded runs it's ≤ 2e-10.

**Q: Why the paired design?**
Same tape, same noise, same costs for all policies → differences are attributable to the policy. Then I compare paired differences across sessions, averaging within session to avoid pseudo-replication.

**Q: Why is buy IS not exactly the negative of sell IS?**
Timing and opportunity flip sign with side, but spread, impact and fees are always costs. So buy IS + sell IS ≈ 2 × (spread + impact + fees + noise), which is exactly the drift-free cost.

---

## 11. Run it yourself

```powershell
cd MarketLens
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/evaluate.py
.\.venv\Scripts\python.exe scripts/evaluate_historical.py
.\.venv\Scripts\python.exe scripts/run.py --port 8000
```
Open http://127.0.0.1:8000 (dashboard) and http://127.0.0.1:8000/docs (API).

Demo script for an interviewer: pick **BATUSDT**, session **2024-01-11**, 09:30–11:30, cut-off **2024-01-10 00:00**, Buy 500 → Compare. Point at the cumulative-execution chart (POV jumps to 100% immediately), the cost decomposition (timing dominates), and the `bar_vwap_proxy` labels. Then switch to the synthetic demo, quantity 2,500, to show capacity-limited partial fills and opportunity cost.
