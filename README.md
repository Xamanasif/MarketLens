# MarketLens

**Market microstructure and execution analytics, with reproducible assumptions.**

A runnable local research application implementing the MarketLens scope in the HSBC Markets Front Office resume: market-data pipelines, intraday analytics, matched TWAP/VWAP/participation comparisons, implementation shortfall, execution-risk sensitivity, FastAPI services and an interactive dashboard.

## Run

Python **3.11 or newer** is required. Extract the ZIP; open the **MarketLens** folder in VS Code.

### Windows

```powershell
cd .\MarketLens
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Port 8000
```

Or install and run manually, without changing PowerShell execution policy:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/run.py --port 8000
```

### macOS / Linux

```bash
cd MarketLens
./run.sh
```

Open **http://127.0.0.1:8000**. API documentation: **http://127.0.0.1:8000/docs**.

First launch creates a synthetic demo if needed. No API keys or model accounts are required. The interface uses local CSS, JavaScript and SVG; it does not depend on a CDN or frontend build tool. Backend persistence is SQLite, numerical/data processing is NumPy/pandas, and the application API is FastAPI. This is a single-user local research workbench, not a brokerage or live trading application. Keep the default loopback binding.

## Five-minute walkthrough

1. Choose **Synthetic six-session market demo**; use the fourth session, Buy, quantity 500, and the default costs. The profile cutoff is midnight before execution.
2. Click **Compare execution policies**. Compare completion, implementation shortfall, VWAP slippage and unfilled quantity. Read the cost decomposition.
3. Increase quantity to 2500 to examine capacity-limited fills. Do not compare partial execution solely by its filled VWAP.
4. Inspect evidence JSON and fills CSV. Repeating an identical request with identical source/code produces the same experiment ID.
5. Open **Experiments** to restore a saved result. Open **Data registry** to see quarantined records.
6. Select **BATUSDT historical aggregate trades (4 sessions)** to analyse real historical inputs. The bundled slice covers 09:00–12:00 UTC, 8–11 January 2024. Use 11 January and 09:30–11:30; set the training cutoff to 10 January 00:00 UTC to use the first two sessions only.
7. Read **Methodology** before interpreting simulated cost differences.

## Data included

- **Synthetic demo:** six generated sessions with prices, trades and quotes. Fixed generation seed; two intentionally invalid trade records are quarantined. Synthetic spreads are explicitly labelled by source.
- **Historical sample:** BATUSDT spot aggregate trades from Binance's public archives for 8–11 January 2024, restricted to 09:00–12:00 UTC. Archive bytes were checked against published SHA256 checksums. Data are trade-only. Quotes, order-book depth and actual order fills are absent.
- `data/datasets/<id>/manifest.json` records provenance, valid/rejected counts and file hashes. `data/source_archives/` contains acquisition URLs, original archives and SHA256 evidence.
- The sample is a small crypto-market example, not an equity/FX institutional execution benchmark. The engine is instrument-agnostic for single-symbol CSV inputs; fees, units, lot-size assumptions and source permissions remain the analyst's responsibility.

Data and derived numerical outputs: CC BY-NC-SA 4.0; see [data/DATA_LICENSE.md](data/DATA_LICENSE.md). Source code: MIT.

Source documentation: https://github.com/binance/binance-public-data
Source terms: https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md

### Import your own CSV

Trades:

```csv
timestamp,symbol,trade_id,price,quantity
2025-01-09T09:30:10Z,ABC,1,100.01,50
```

Optional quotes:

```csv
timestamp,symbol,bid,ask
2025-01-09T09:30:00Z,ABC,100.00,100.02
```

Use the Data registry form or:

```bash
python scripts/import_csv.py trades.csv --quotes quotes.csv --name "ABC historical tape" --description "Source, dates and terms"
```

Timestamps must be timezone-aware ISO-8601. One symbol per dataset. Required columns are enforced. Invalid numeric values, crossed quotes and duplicate IDs/timestamps are quarantined. All-invalid files, mixed symbols, missing schema and files over the limits are rejected. Maximum 100,000 records per input file. Out-of-order rows are stably sorted after UTC normalization. Raw files and rejected records are retained.

### Re-download the public sample

```bash
python scripts/import_binance.py --symbol BATUSDT --date 2024-01-08 --date 2024-01-09 --date 2024-01-10 --date 2024-01-11 --start-time 09:00 --end-time 12:00
```

This command needs external network access. Binance spot timestamps from 2025 use microseconds; the adapter handles milliseconds and microseconds without using float timestamp arithmetic. A checksum failure stops the import. Large archives are bounded; select a smaller date/symbol or prepare explicit slices rather than silently truncating data. Local archive mode requires an expected checksum. Time filters are start-inclusive/end-exclusive in UTC.

## Research and evaluation

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py
python scripts/evaluate_historical.py
```

The synthetic study evaluates two sides × two order sizes × three held-out sessions, against all three policies. The historical study uses two earlier sessions for the profile and two later sessions for execution. Both retain every policy's results, including losses and incomplete orders.

Reports live in `reports/`. Full runs, fill records, config, source hashes, code hash and risk scenarios are saved in the local SQLite ledger. Evaluation scripts are deterministic for unchanged code, data and seeds. API batch comparisons reject overlapping windows. The evaluation scripts resample whole sessions after averaging configurations within each session; the API `/api/batches` resamples whole submitted windows. Small/dependent samples do not support reliable statistical conclusions.

## Algorithms and metrics

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for precise equations and timing conventions. Important boundaries:

- The policy cannot use same-minute realised volume to set a participation request. It can affect realised fill capacity only in the simulator.
- VWAP scheduling uses earlier-session volume profiles. Full execution-window VWAP is used solely as an ex-post benchmark.
- Quotes are backward-matched to minute starts and have a maximum age. Trade-only pricing uses an explicitly retrospective minute-VWAP proxy and assumed spread.
- Prices are an unchanging market tape. Temporary impact is an assumption, not an estimated or causal market-impact model.
- Unfilled shares/tokens remain unfilled; opportunity cost marks them to the final trade price.
- Noise-risk intervals condition on a fixed market path. They are not market VaR or predictive confidence intervals for future sessions.
- No realised savings, production usage, profitable strategy or exchange execution is established by these experiments.

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Version and request count |
| GET / POST | `/api/datasets` | Registry / validated CSV import |
| GET | `/api/datasets/{id}/analytics` | Bars, spreads, liquidity and volatility diagnostics |
| GET | `/api/datasets/{id}/quarantine` | Rejected rows and reasons |
| POST | `/api/experiments` | Matched three-policy experiment |
| GET | `/api/experiments` | Last 100 saved experiments |
| GET | `/api/experiments/{id}` | Full reproducibility artifact |
| GET | `/api/experiments/{id}/export.json` | Evidence download |
| GET | `/api/experiments/{id}/fills.csv` | Full fill ledger |
| POST | `/api/batches` | Non-overlapping matched-window comparison |

`Config` schema is documented in `/docs`; seeds, quote age, side, capacity, participation, fee, assumed spread, impact and fill noise are configurable. Quantity must be positive; numbers must be finite. Execution windows are one UTC session, at most six hours, aligned to minute boundaries and covered by the data. Profile cutoff must be no later than execution start. Missing training-minute coverage rejects an experiment instead of substituting future volumes.

## Browser acceptance checks

```bash
pip install playwright==1.62.0
python -m playwright install chromium
python scripts/browser_check.py
```

The optional harness starts an isolated server/database and exercises nine browser checks, including a 390px mobile layout check. All nine pass with headless Chromium; see `docs/STATUS.md`.

## Docker and CI

```bash
docker build -t marketlens .
docker run --rm -p 127.0.0.1:8000:8000 -v marketlens-data:/app/data marketlens
```

The Docker image has been built and run, and the CI workflow's steps pass inside it (Linux, Python 3.12). Remote GitHub Actions execution has not been run. A mounted volume retains data. Do not expose this unauthenticated workbench publicly. For shared production use, add authenticated workspaces, a task queue, authorization, deployment-specific request limits and resource isolation.

## Repository map

```text
MarketLens/
  marketlens/       ingestion, analytics, simulation, API, persistence
    static/        dashboard, local styles, charts and interaction code
  scripts/         launch, import, synthetic/historical evaluation, browser checks
  tests/           numerical invariants, leakage, parsing, API and concurrency tests
  data/            versioned demo and historical market data
  reports/         reproducible evaluation artifacts and verification record
  docs/            methodology, architecture, interview guide, master explanation, resume evidence, status
  run.ps1          Windows launcher
  run.sh           macOS/Linux launcher
```

The project contains no secrets or brokerage credentials. SQLite records research runs and can be regenerated in a separate home with `MARKETLENS_HOME`. Do not edit original data when reproducing an experiment; register a new dataset instead.
