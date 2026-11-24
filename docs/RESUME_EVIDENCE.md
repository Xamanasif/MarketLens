# Resume evidence map

## The agreed HSBC bullets

> Engineered market-data pipelines to analyse liquidity, volatility and intraday patterns; compared TWAP, VWAP and participation-based execution under explicit fill, fee and slippage assumptions.

Evidence: `marketlens/data.py`, `analytics.py`, `engine.py`, bundled historical and synthetic datasets, `reports/historical_evaluation.json`, `reports/evaluation.json`. VWAP is specifically a historical-profile schedule. Participation requests use lagged volume. Real sample data are trade-only, and spreads are assumed.

> Evaluated implementation shortfall and execution risk across matched trading scenarios; delivered reproducible experiments, FastAPI services and an interactive dashboard separating observed data from simulated fills.

Evidence: `engine.py` cost decomposition and noise sensitivity; `scripts/evaluate*.py`; `store.py`; typed routes in `app.py`; frontend in `marketlens/static/`; JSON/CSV exports and source/code fingerprints. Execution risk here means conditional fill-noise sensitivity, not a full market-risk model. Nine real-browser acceptance checks pass; Windows and Linux reproduce identical experiment IDs.

## Defensible project wording

- Built a Python/FastAPI market-data and execution-research workbench comparing TWAP, historical-profile VWAP and lagged-volume participation under explicit cost and capacity assumptions.
- Evaluated signed implementation shortfall, completion and cost decomposition on matched scenarios, distinguishing historical trade observations from simulated fills and assumed spreads.
- Implemented reproducible experiment tracking, SQLite persistence, validation/quarantine, interactive charts and evidence exports; tested numerical accounting, information timing, API behaviour and concurrent duplicate requests.

Do not claim institutional deployment, actual cost savings, real order fills, quote-level analysis on trade-only inputs, or superiority established by this small sample. Metrics in the evaluation artifacts describe this implementation's sample, not a business outcome.
