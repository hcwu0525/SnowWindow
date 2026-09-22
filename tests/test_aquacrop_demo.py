import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from aquacrop_demo.physics import planting_windows, reference_et
from aquacrop_demo.pipeline import choose_parameter
from aquacrop_demo.model import Experiment


def test_et0_seasonality_and_radiation_response():
    w = pd.DataFrame({"Date": pd.to_datetime(["2024-01-15", "2024-07-15"]), "T2M_MIN": [15., 15.], "T2M_MAX": [25., 25.],
                      "RH2M": [60., 60.], "WS2M": [2., 2.], "PS": [100., 100.], "ALLSKY_SFC_SW_DWN": [4., 22.]})
    a = reference_et(w, 42, 100)
    assert (a.ReferenceET >= 0).all()
    assert a.ReferenceET.iloc[1] > a.ReferenceET.iloc[0]
    higher = w.copy(); higher["ALLSKY_SFC_SW_DWN"] += 2
    # In the warm growing-season case, added radiation increases ET0.
    # Winter cloudiness/longwave correction prevents a universal monotonic claim.
    assert reference_et(higher, 42, 100).ReferenceET.iloc[1] > a.ReferenceET.iloc[1]


def test_windows_keep_disjoint_sets_ties_and_boundary():
    f = pd.DataFrame({"offset_days": [-20, -15, -10, -5, 0], "planting_date": ["2023-04-01", "2023-04-06", "2023-04-11", "2023-04-16", "2023-04-21"],
                      "dry_yield_Mg_ha": [10, 9.6, 8, 10, 9.6], "status": ["matured"] * 5})
    result = planting_windows(f, [0.95])[0]
    assert result["segments"] == [["2023-04-01", "2023-04-06"], ["2023-04-16", "2023-04-21"]]
    assert len(result["best_dates"]) == 2 and result["edge_peak"]
    f.loc[0, "status"] = "not_matured"
    assert "2023-04-01" not in planting_windows(f, [0.95])[0]["dates"]
    f.loc[4, "status"] = "insufficient_thermal_time"
    assert planting_windows(f, [0.95])[0]["adjacent_abnormal_candidate"]


@pytest.mark.parametrize("status,yield_value", [("matured", 0), ("execution_failed", np.nan), ("crop_died", 20)])
def test_no_window_without_positive_mature_yield(status, yield_value):
    f = pd.DataFrame({"offset_days": [0], "planting_date": ["2023-05-01"], "status": [status], "dry_yield_Mg_ha": [yield_value]})
    assert planting_windows(f)[0]["status"] == "no_positive_mature_yield"


def test_calibration_does_not_use_test_labels_and_rejects_missing_pairs():
    units = [{"unit_id": "train", "observed_pollen_DAP": 60}]
    r = [{"unit_id": "train", "phenology_scale": .9, "flowering_proxy_DAP": 60, "status": "matured"},
         {"unit_id": "train", "phenology_scale": 1., "flowering_proxy_DAP": 66, "status": "matured"},
         {"unit_id": "test", "phenology_scale": .9, "flowering_proxy_DAP": 90, "status": "matured"},
         {"unit_id": "test", "phenology_scale": 1., "flowering_proxy_DAP": 60, "status": "matured"}]
    chosen, _ = choose_parameter(r, units, "phenology_scale", "observed_pollen_DAP", 1)
    assert chosen == .9
    r[0]["status"] = "insufficient_thermal_time"
    chosen, losses = choose_parameter(r, units, "phenology_scale", "observed_pollen_DAP", 1)
    assert chosen == 1 and np.isinf(losses[0]["training_mae"])


@pytest.fixture(scope="module")
def experiment():
    cfg = yaml.safe_load(Path("aquacrop_demo/config.yaml").read_text())
    if not (Path(cfg["output_dir"]) / "weather_manifest.json").exists(): pytest.skip("Run prepare first")
    return Experiment(cfg)


def test_zero_offset_reproducibility_and_preplant_comparison(experiment):
    u = experiment.units[1]
    a = experiment.run(u, store_daily=True, force=True)
    b = experiment.run(u, store_daily=True, force=True)
    assert a["status"] == b["status"] == "matured"
    assert a["dry_yield_Mg_ha"] == b["dry_yield_Mg_ha"]
    assert a["actual_planting_date"] == u["planting_date"]
    assert a["water_balance_max_abs_mm_day"] < 1e-7
    early = experiment.run(u, offset=-20, store_daily=True, force=True)
    d1 = pd.read_parquet(experiment.cache / (a["run_id"] + ".parquet"))
    d2 = pd.read_parquet(experiment.cache / (early["run_id"] + ".parquet"))
    before = pd.Timestamp(early["planting_date"])
    # Before the earliest intervention, all soil-water paths must coincide.
    np.testing.assert_allclose(d1.loc[d1.Date < before, "soil_water_mm"], d2.loc[d2.Date < before, "soil_water_mm"], atol=1e-10)
    assert a["preplant_soil_water_range_mm"] > 0
    prof = pd.read_csv(experiment.cache / (a["run_id"] + ".soil.csv"))
    assert np.isclose(prof.dz.sum(), 2) and np.allclose(prof.dz, .1)


def test_insufficient_heat_is_recorded_not_zero_filled(experiment):
    r = experiment.run(experiment.units[4], scale=1.2, force=True)
    assert r["status"] == "insufficient_thermal_time"
    assert r["dry_yield_Mg_ha"] is None
    assert "not enough growing degree days" in r["error"]


def test_initial_state_sensitivity_is_real_and_root_cap_is_explicit(experiment):
    u = experiment.units[1]
    a = experiment.run(u, water_pct=25, force=True)
    b = experiment.run(u, water_pct=75, force=True)
    assert a["status"] == b["status"] == "matured"
    assert b["initial_soil_water_mm"] > a["initial_soil_water_mm"]
    c = experiment.run(u, root_scale=1.2, force=True)
    assert c["root_depth_clipped_by_profile"] and np.isclose(c["effective_max_root_depth_m"], 1.9)
