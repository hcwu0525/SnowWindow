from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from aquacrop_demo.model import Experiment


@pytest.fixture(scope="module")
def crossyear_experiment():
    path = Path("outputs/aquacrop_crossyear/config.yaml")
    if not path.exists():
        pytest.skip("Prepare cross-year weather first")
    return Experiment(yaml.safe_load(path.read_text()))


def test_next_year_weather_and_december_sowing(crossyear_experiment):
    e = crossyear_experiment
    unit = next(u for u in e.units if u["Env"] == "INH1_2023")
    assert len(e.weather[unit["Env"]]) == 731  # 2024 leap day retained
    result = e.run(unit, planting_date="2023-12-31", scale=.95, hi0=.35, store_daily=True)
    assert result["status"] == "matured"
    assert result["maturity_date"].startswith("2024-")
    assert result["simulation_end_date"] == "2024-12-30"
    daily = pd.read_parquet(e.cache / (result["run_id"] + ".parquet"))
    assert daily.Date.max().year == 2024
    assert result["water_balance_max_abs_mm_day"] < 1e-7


def test_observed_planting_stays_equal_to_same_year_run(crossyear_experiment):
    e = crossyear_experiment
    unit = next(u for u in e.units if u["Env"] == "INH1_2023")
    a = e.run(unit, planting_date=unit["planting_date"], scale=.95, hi0=.35)
    old_cfg = yaml.safe_load(Path("aquacrop_demo/config.yaml").read_text())
    b = Experiment(old_cfg).run(unit, planting_date=unit["planting_date"], scale=.95, hi0=.35)
    assert a["status"] == b["status"] == "matured"
    assert np.isclose(a["dry_yield_Mg_ha"], b["dry_yield_Mg_ha"], atol=1e-9, rtol=0)


def test_february_29_harvest_rule_is_avoided(crossyear_experiment):
    e = crossyear_experiment
    unit = next(u for u in e.units if u["Env"] == "INH1_2023")
    result = e.run(unit, planting_date="2023-03-01", scale=.95, hi0=.35)
    assert result["status"] != "execution_failed"
    assert result["leap_day_harvest_rule_adjusted"]
    assert result["simulation_end_date"] == "2024-02-28"
