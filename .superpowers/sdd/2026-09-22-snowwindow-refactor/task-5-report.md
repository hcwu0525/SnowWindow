# Task 5 report — full-year scan and report

- Added calendar-date and contiguous-window logic with tests for leap years,
  disjoint windows, abnormal states, and tied maxima.
- Materialized the reviewed six-environment AquaCrop cross-year cache into the
  new experiment contract with explicit source hash and parameter mapping.
- Acceptance output contains 4,380 unique rows: six environments, two
  parameter sets, and 365 requested planting dates.
- Wrote Parquet/CSV summaries, JSON/CSV 90% and 95% windows, six figures, and a
  Chinese Markdown report.
- Abnormal statuses remain in the scan and are excluded from yield windows.

Limitation: this acceptance run reuses the existing complete NASA POWER model
cache; it does not reinterpret the incomplete 2024 G2F weather as complete.
