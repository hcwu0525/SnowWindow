"""Baseline, deliberately small calibration, held-out validation and scenarios."""
from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .data import write_json
from .model import Experiment
from .physics import planting_windows

_WORKER = None


def _initialize_worker(cfg):
    global _WORKER
    _WORKER = Experiment(cfg)


def _run_worker(task):
    unit, options = task
    return _WORKER.run(unit, **options)


def run_many(experiment, tasks):
    if not tasks: return []
    if experiment.cfg.get("workers", 1) <= 1:
        return [experiment.run(unit, **options) for unit, options in tasks]
    with ProcessPoolExecutor(max_workers=experiment.cfg["workers"], mp_context=multiprocessing.get_context("spawn"),
                             initializer=_initialize_worker, initargs=(experiment.cfg,)) as pool:
        results = []
        for i, r in enumerate(pool.map(_run_worker, tasks), 1):
            results.append(r)
            if i % 15 == 0 or i == len(tasks): print(f"Completed {i}/{len(tasks)} runs", flush=True)
    return results


def baseline(cfg):
    e = Experiment(cfg)
    unit = sorted([u for u in e.units if u["site"] == e.units[0]["site"]], key=lambda u: -u["year"])[0]
    results = run_many(e, [(unit, {"offset": offset, "store_daily": True}) for offset in cfg["offsets_days"]])
    pd.DataFrame(results).to_csv(e.out / "milestone_a.csv", index=False)
    # Baseline at observed planting dates for all units, used by calibration/validation.
    original = run_many(e, [(u, {"store_daily": True}) for u in e.units])
    pd.DataFrame(original).to_csv(e.out / "baseline_original_dates.csv", index=False)
    print(pd.DataFrame(results)[["Env", "offset_days", "dry_yield_Mg_ha", "maturity_date", "status"]].to_string(index=False), flush=True)
    return results


def _grid(spec):
    lo, hi, step = spec
    return np.round(np.linspace(lo, hi, round((hi - lo) / step) + 1), 8).tolist()


def _observations(e):
    return pd.DataFrame(e.units)[["unit_id", "Env", "site", "year", "split", "observed_pollen_DAP", "observed_silk_DAP", "observed_dry_yield_Mg_ha"]]


def choose_parameter(results, units, column, observed, default):
    rows = []
    unit_ids = {u["unit_id"] for u in units}
    observed_map = {u["unit_id"]: u[observed] for u in units}
    predicted = "flowering_proxy_DAP" if observed == "observed_pollen_DAP" else "dry_yield_Mg_ha"
    for value, group in pd.DataFrame(results).groupby(column):
        g = group.loc[group.unit_id.isin(unit_ids)]
        pairs = [(r[predicted], observed_map[r["unit_id"]]) for r in g.to_dict("records") if r["status"] == "matured" and pd.notna(r[predicted])]
        # Failed/dead/not mature candidates must not get a deceptively good
        # loss by silently discarding the difficult training environment.
        loss = float(np.mean([abs(p - o) for p, o in pairs])) if len(pairs) == len(unit_ids) else float("inf")
        rows.append({column: float(value), "training_mae": loss, "n_training_units": len(unit_ids), "n_valid_pairs": len(pairs)})
    finite = [r for r in rows if np.isfinite(r["training_mae"])]
    if not finite: raise ValueError("No calibration candidate valid on all training units")
    selected = min(finite, key=lambda r: (round(r["training_mae"], 10), abs(r[column] - default), r[column]))[column]
    return selected, rows


def calibrate(cfg):
    e = Experiment(cfg)
    folds = [{"name": "heldout_year", "train_ids": [u["unit_id"] for u in e.units if u["split"] == "train"],
              "test_ids": [u["unit_id"] for u in e.units if u["split"] == "test"]}]
    for site in sorted({u["site"] for u in e.units}):
        folds.append({"name": f"leave_site_{site}", "train_ids": [u["unit_id"] for u in e.units if u["site"] != site],
                      "test_ids": [u["unit_id"] for u in e.units if u["site"] == site]})
    # Simulation candidate outputs may be shared across folds; ONLY training
    # labels enter each fold's objective or parameter selection.
    phen_results = run_many(e, [(u, {"scale": scale}) for scale in _grid(cfg["phenology_scale_grid"]) for u in e.units])
    losses, parameters = [], []
    for fold in folds:
        train = [u for u in e.units if u["unit_id"] in fold["train_ids"]]
        scale, rows = choose_parameter(phen_results, train, "phenology_scale", "observed_pollen_DAP", 1.0)
        losses.extend({**r, "fold": fold["name"], "phase": "phenology"} for r in rows)
        parameters.append({**fold, "phenology_scale": scale})
    hi_results = {}
    for scale in sorted({p["phenology_scale"] for p in parameters}):
        hi_results[scale] = run_many(e, [(u, {"scale": scale, "hi0": hi}) for hi in _grid(cfg["harvest_index_grid"]) for u in e.units])
    for param in parameters:
        train = [u for u in e.units if u["unit_id"] in param["train_ids"]]
        hi, rows = choose_parameter(hi_results[param["phenology_scale"]], train, "HI0", "observed_dry_yield_Mg_ha", e.base["HI0"])
        losses.extend({**r, "fold": param["name"], "phase": "yield"} for r in rows)
        param.update(HI0=hi, phenology_boundary=param["phenology_scale"] in [cfg["phenology_scale_grid"][0], cfg["phenology_scale_grid"][1]],
                     hi0_boundary=hi in [cfg["harvest_index_grid"][0], cfg["harvest_index_grid"][1]],
                     parameter_source="fold training observations only; generic crop; no environment/hybrid-specific adjustment")
    pd.DataFrame(losses).to_csv(e.out / "calibration_search.csv", index=False)
    write_json(e.out / "calibration_parameters.json", parameters)
    write_json(e.out / "calibration_manifest.json", {"thermal_keys_scaled_together": ["Emergence", "MaxRooting", "Senescence", "Maturity", "HIstart", "Flowering", "YldForm"],
               "fixed_parameters": "all other parameters, including WP, CGC, CDC, thermal thresholds, water stress, density, soil and initialization",
               "flowering_observation_proxy": "first simulated end-of-day crossing of HIstart versus observed 50% pollen DAP; different biological definitions",
               "maturity_not_independently_calibrated": True, "yield_basis": "dry matter; observed 15.5% moisture yield * 0.845",
               "shared_candidate_simulations": "test outcomes never enter a fold loss; labels from other folds may train those other folds"})
    print(json.dumps(parameters, indent=2, ensure_ascii=False), flush=True)
    return parameters


def metrics(group):
    rows = []
    for target, prediction, obs in [("flowering_proxy_days", "flowering_proxy_DAP", "observed_pollen_DAP"),
                                    ("dry_yield_Mg_ha", "dry_yield_Mg_ha", "observed_dry_yield_Mg_ha")]:
        good = group.loc[group.status.eq("matured")].dropna(subset=[prediction, obs])
        residual = good[prediction].to_numpy() - good[obs].to_numpy()
        rows.append({"target": target, "n": len(good), "n_excluded": len(group) - len(good),
                     "mae": float(np.abs(residual).mean()) if len(good) else None,
                     "rmse": float(np.sqrt(np.mean(residual ** 2))) if len(good) else None,
                     "bias": float(residual.mean()) if len(good) else None})
    return rows


def validate(cfg):
    e = Experiment(cfg)
    params = json.loads((e.out / "calibration_parameters.json").read_text())
    pairs = []
    for param in params:
        for split, ids in [("train", param["train_ids"]), ("test", param["test_ids"])]:
            units = [u for u in e.units if u["unit_id"] in ids]
            modes = [("default", 1.0, e.base["HI0"]), ("phenology_only", param["phenology_scale"], e.base["HI0"]),
                     ("phenology_and_yield", param["phenology_scale"], param["HI0"])]
            for mode, scale, hi in modes:
                results = run_many(e, [(u, {"scale": scale, "hi0": hi, "store_daily": param["name"] == "heldout_year"}) for u in units])
                pairs.extend({**r, "fold": param["name"], "validation_split": split, "parameter_set": mode} for r in results)
    data = pd.DataFrame(pairs).merge(_observations(e).drop(columns=["Env", "site", "year", "split"]), on="unit_id", validate="many_to_one")
    data.to_csv(e.out / "validation_predictions.csv", index=False)
    rows = []
    for (fold, split, mode), g in data.groupby(["fold", "validation_split", "parameter_set"]):
        rows.extend({**r, "fold": fold, "split": split, "parameter_set": mode} for r in metrics(g))
    pd.DataFrame(rows).to_csv(e.out / "validation_metrics.csv", index=False)
    print(pd.DataFrame(rows).loc[lambda f: f.fold.eq("heldout_year") & f.split.eq("test")].to_string(index=False), flush=True)
    return rows


def scenarios(cfg):
    e = Experiment(cfg)
    param = next(p for p in json.loads((e.out / "calibration_parameters.json").read_text()) if p["name"] == "heldout_year")
    modes = [("default", 1.0, e.base["HI0"]), ("phenology_only", param["phenology_scale"], e.base["HI0"]),
             ("phenology_and_yield", param["phenology_scale"], param["HI0"])]
    rows = []
    for mode, scale, hi in modes:
        print(f"Scenario parameter set: {mode}", flush=True)
        results = run_many(e, [(u, {"offset": d, "scale": scale, "hi0": hi, "store_daily": True}) for u in e.units for d in cfg["offsets_days"]])
        rows.extend({**r, "parameter_set": mode, "sensitivity": "baseline"} for r in results)
    for factor, values in cfg["input_sensitivity"].items():
        for value in values:
            options = {"water_pct": value} if factor == "initial_available_water_pct" else {"root_scale": value}
            label = f"{factor}={value}"
            print(f"Sensitivity: {label}", flush=True)
            results = run_many(e, [(u, {"offset": d, "scale": param["phenology_scale"], "hi0": param["HI0"], **options}) for u in e.units for d in cfg["offsets_days"]])
            rows.extend({**r, "parameter_set": "phenology_and_yield", "sensitivity": label} for r in results)
    data = pd.DataFrame(rows)
    data.to_csv(e.out / "scenario_summary.csv", index=False)
    window_rows = []
    for (unit_id, mode, sensitivity), group in data.groupby(["unit_id", "parameter_set", "sensitivity"]):
        window_rows.extend({**r, "unit_id": unit_id, "Env": group.Env.iloc[0], "site": group.site.iloc[0], "year": int(group.year.iloc[0]),
                            "parameter_set": mode, "sensitivity": sensitivity} for r in planting_windows(group, cfg["window_fractions"]))
    write_json(e.out / "planting_windows.json", window_rows)
    flat = [{**r, "dates": json.dumps(r["dates"]), "segments": json.dumps(r["segments"]), "best_dates": json.dumps(r.get("best_dates", []))} for r in window_rows]
    pd.DataFrame(flat).to_csv(e.out / "planting_windows.csv", index=False)
    return rows
