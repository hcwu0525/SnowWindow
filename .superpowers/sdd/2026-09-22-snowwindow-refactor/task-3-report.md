# Task 3 report — AquaCrop adapter

## Files changed

- `pyproject.toml`
- `src/snowwindow/models/__init__.py`
- `src/snowwindow/models/aquacrop/__init__.py`
- `src/snowwindow/models/aquacrop/physics.py`
- `src/snowwindow/models/aquacrop/adapter.py`
- `tests/snowwindow/test_aquacrop_adapter.py`

No raw data, prior outputs, legacy `aquacrop_demo/` code, or legacy tests were modified.

## RED/GREEN evidence

- Tests were introduced before the adapter implementation; initial collection failed because `snowwindow.models.aquacrop` did not exist.
- Focused adapter suite: `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_aquacrop_adapter.py` — 30 passed in 4.79 seconds.
- Full suite: `.venv-py39/bin/python -m pytest -q` — 107 passed in 75.87 seconds.
- `.venv-py39/bin/ruff check src tests/snowwindow` — passed.
- `.venv-py39/bin/ruff format --check src tests/snowwindow` — 16 files formatted.

## Implemented behavior

- Added the AquaCrop 3.1.0 adapter with strict request/weather/profile/parameter validation and stable status mapping.
- Added FAO-56 daily ET0, preserving raw values and clipping only AquaCrop input to 0.1 mm/day.
- Added shared thermal scaling, HI0, initial water, root-depth, population, rainfed-only, January 1 initialization, exact sowing intervention, recurring-calendar leap adjustment, and flowering proxy behavior.
- Added mature/abnormal/failure summaries, preplant water metrics, soil bounds, and daily/total water-balance residuals.
- Added content-addressed summary caching and optional atomic daily/crop/soil artifacts. Cache identity excludes output location and `save_daily`; missing requested daily artifacts force a rerun.

## Fingerprints

- Adapter source SHA-256: `0ca98fda4197f12ebc020dd2a158cc893601fb7fe6f5c57d6d836b623e29038d`
- AquaCrop source SHA-256: `c583c74a291206588e0f848fa8f9b2b1987c95fc6a7f922ef3c09e6b19c3e54f`
- Bundled smoke dry yield: `8.940139992051638 Mg/ha`

## Limitations and concerns

- This adapter supports one homogeneous AquaCrop soil profile and rainfed management only.
- `HIstart` crossing is a flowering proxy, not an independent pollen event.
- AquaCrop 3.1.0 suppresses public imports when pytest receives a literal `-m`; adapter tests must be selected without pytest's `-m` option.
- Model source fingerprinting hashes installed Python sources and therefore intentionally changes with the installed package contents.
