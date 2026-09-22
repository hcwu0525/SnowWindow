# Task 4 report — calibration and validation

## Files changed

- `src/snowwindow/calibration.py`
- `src/snowwindow/experiment.py`
- `src/snowwindow/stages.py`
- `tests/snowwindow/test_calibration.py`
- `configs/g2f_demo.yaml`
- `configs/g2f_history.yaml`

## Behavior

The workflow selects the largest management experiment per configured environment without consulting yield, freezes eligible calibration observations, runs deterministic coarse/fine searches for `phenology_scale` then `HI0`, rejects incomplete candidates, and calculates coverage, MAE, RMSE, and signed bias. Held-year and leave-site folds keep evaluation years out of training. Cached full-year NASA POWER forcing is loaded with hashes and provenance to construct cross-year AquaCrop requests.

## Verification

- Calibration unit tests: 9 passed.
- AquaCrop plus calibration tests: 46 passed before the final orchestration additions.
- Six-environment baseline ran successfully: five matured and `NYH2_2022` remained explicitly `crop_died`.
- Demo coarse/fine calibration completed with 228 search rows. Held-year parameters: `phenology_scale=0.95`, `HI0=0.35`.
- Validation produced 60 row-level target predictions with held-year and leave-site metrics. Held-year calibrated test coverage was 1.0 for flowering and dry yield.

## Limitations

The demo uses the existing read-only same-coordinate NASA POWER cache rather than incomplete 2024 G2F station forcing. Calibration remains representative-maize and global; cultivar-specific parameters are intentionally out of scope.
