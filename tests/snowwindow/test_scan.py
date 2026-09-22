from __future__ import annotations

import pandas as pd

from snowwindow.scan import calendar_dates, derive_planting_windows


def test_calendar_dates_preserve_leap_year() -> None:
    assert len(calendar_dates(2023)) == 365
    assert len(calendar_dates(2024)) == 366


def test_windows_use_only_mature_positive_yield_and_preserve_segments() -> None:
    frame = pd.DataFrame(
        {
            "planting_date": pd.date_range("2023-04-01", periods=6).date,
            "status": [
                "matured",
                "matured",
                "not_matured",
                "matured",
                "matured",
                "execution_failed",
            ],
            "dry_yield_mg_ha": [10.0, 9.6, None, 9.7, 10.0, None],
        }
    )

    window = derive_planting_windows(frame, (0.95,))[0]

    assert window["dates"] == [
        "2023-04-01",
        "2023-04-02",
        "2023-04-04",
        "2023-04-05",
    ]
    assert window["segments"] == [
        ["2023-04-01", "2023-04-02"],
        ["2023-04-04", "2023-04-05"],
    ]
    assert window["best_dates"] == ["2023-04-01", "2023-04-05"]
