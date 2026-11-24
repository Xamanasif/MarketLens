# Data attribution and licensing

Historical BATUSDT aggregate-trade data: Binance Vision public dataset archives,
8–11 January 2024, UTC 09:00–12:00 slice. Source links and original SHA256
checksums are preserved in `source_archives/*-sources.json`.

Source: https://data.binance.vision/
Provider terms: https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md

The provider's terms retrieved on 24 November 2026 designate the datasets as
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International:
https://creativecommons.org/licenses/by-nc-sa/4.0/

Changes made here: timezone normalization, selecting an explicit UTC time
window, consolidating four sessions, validated CSV storage and derived
minute bars / execution-research results. No endorsement by Binance is implied.

The bundled data and data-derived numerical reports / experiment-ledger content
are provided under CC BY-NC-SA 4.0 with this attribution. Keep attribution and
the same licence for redistributed derivative data. This package is an
educational, non-commercial research demonstration. Source-code licensing is
separate (MIT; see ../LICENSE). The synthetic data were generated for this
project and are also released under CC BY-NC-SA 4.0 for consistent data-package
handling.
