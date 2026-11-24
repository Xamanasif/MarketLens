# Build and verification status

Implemented for the HSBC resume scope on 24 November 2026. Completed and re-verified on Windows and Linux the same day.

## Verified

- **42 unit/API/regression tests pass** on Windows 11 / Python 3.13.5 and on Linux / Python 3.12 (inside the project Docker image). Windows output is in `reports/test_results.txt`.
- **Nine real-browser acceptance checks pass** (`scripts/browser_check.py`, Playwright 1.62.0, headless Chromium): dashboard load, provenance, three-policy rendering, execution chart, evidence export, history restore, invalid-cutoff error, mobile layout without horizontal overflow, no uncaught JavaScript errors.
- **Cross-platform reproducibility:** Windows and Linux produce the same synthetic dataset ID (`22a2df81ac5154c0`), the same file hashes, the same code fingerprint and identical experiment IDs and metrics for both evaluation studies.
- **Windows launcher** (`run.ps1`) installs dependencies and serves the app; **Docker** image builds, serves `/api/health` and runs experiments on a loopback-published port.
- The steps in `.github/workflows/check.yml` (install, unit tests, synthetic evaluation) were executed inside the Linux container. Remote GitHub Actions has not run because the project is not in a hosted repository.
- FastAPI routes, dashboard/static-file serving, import validation, saved history, JSON/CSV export and batch comparisons are exercised through the ASGI TestClient and against a live server.
- Deterministic synthetic demo: 2,160 valid trade records; 720 quote records; two deliberately rejected trade records preserved in quarantine.
- Historical sample: 8,809 BATUSDT aggregate trades from four January 2024 UTC sessions, restricted to 09:00–12:00. Original archive SHA256 checks matched the provider's published checksums.
- Synthetic evaluation: 12 matched configurations, 36 policy evaluations, three execution sessions after three profile-training sessions.
- Historical evaluation: eight matched configurations, 24 policy evaluations, two execution sessions after two profile-training sessions.
- Numerical cost decompositions reconcile within 2e-10 cash units in the recorded evaluations.
- Tests cover buy/sell signs, zero-volume fills, capacity limits, unfilled opportunity cost, lagged-volume POV, profile cutoffs, future-volume leakage, stale/future quotes, data integrity, platform-independent dataset identity, millisecond/microsecond conversion, non-finite numbers and concurrent duplicate requests.

## Fixed during completion

1. **Platform-dependent dataset identity.** `pandas.to_csv()` emitted CRLF on Windows and `Path.write_text` translated newlines again, so the synthetic demo hashed differently and produced different experiment IDs (and a duplicate registry entry). CSV output now uses explicit `\n` and stored files are written with `newline=''`. Two regression tests pin the demo ID and byte-for-byte raw storage.
2. **Browser harness blocked by the app's own CSP.** Playwright evaluates string predicates with `eval`, which `script-src 'self'` forbids. The test browser now uses `bypass_csp=True`; the application's policy is unchanged.
3. **Mobile horizontal overflow.** Grid tracks could not shrink below content width (page was 486px wide at a 390px viewport). Grids now use `minmax(0,1fr)`, and metrics stack below 520px.

Because `data.py` changed, the engine code fingerprint changed, so recorded experiment IDs differ from the first build. All metrics and bootstrap results are numerically identical to the first build.

## Not verified

- macOS execution of `run.sh`.
- Remote GitHub Actions execution.
- No public production deployment or live execution.

## Interpretation limits

Historical trade inputs are observations; all order fills, assumed spreads, fee/impact parameters and noise scenarios remain simulations. The synthetic demo has generated quotes. Neither dataset supports claims of actual trading savings, order-book queue realism, or institutional production performance. The historical comparison has only two evaluation sessions; retain unfavorable results and avoid statistical-superiority claims. On the BATUSDT sample, POV completes the order within about two minutes, so per-row POV-versus-TWAP differences mainly reflect price drift; side-averaged comparisons isolate cost components.

## Reproduce

Run the README installation commands, then:

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py
python scripts/evaluate_historical.py
pip install playwright==1.62.0 && python -m playwright install chromium
python scripts/browser_check.py
```

Recorded reports identify exact experiment IDs, dataset hashes and code fingerprint. Reading an old run does not rerun it. Re-running evaluation is permitted; this is a descriptive reproducible study, not a locked one-time statistical trial.
