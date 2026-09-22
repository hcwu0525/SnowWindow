"""Pinned OSPy adapter; all experiments use this same full simulation path."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
import traceback
from pathlib import Path

import aquacrop
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Crop, InitialWaterContent, IrrigationManagement, Soil
from aquacrop.entities.crops.crop_params import crop_params
from aquacrop.utils import get_filepath, prepare_weather

from .data import sha256_file, write_json

THERMAL_KEYS = ("Emergence", "MaxRooting", "Senescence", "Maturity", "HIstart", "Flowering", "YldForm")


def model_fingerprint():
    h = hashlib.sha256()
    root = Path(aquacrop.__file__).parent
    for path in sorted(root.rglob("*.py")):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def smoke(cfg):
    assert importlib.metadata.version("aquacrop") == cfg["model_version"]
    start = time.perf_counter()
    m = AquaCropModel("1979/10/01", "1980/05/30", prepare_weather(get_filepath("tunis_climate.txt")),
                     Soil("SandyLoam"), Crop("Wheat", "10/01"), InitialWaterContent(value=["FC"]))
    m.run_model(till_termination=True)
    stats = m.get_simulation_results()
    assert len(stats) == 1 and np.isfinite(stats["Dry yield (tonne/ha)"].iloc[0])
    result = {"python": platform.python_version(), "platform": platform.platform(), "aquacrop": importlib.metadata.version("aquacrop"),
              "model_source_sha256": model_fingerprint(), "elapsed_seconds": time.perf_counter() - start,
              "example_final_results": stats.to_dict("records"),
              "outputs": {method: list(getattr(m, method)().columns) for method in ["get_simulation_results", "get_crop_growth", "get_water_flux", "get_water_storage"]},
              "default_crop_parameter_library": crop_params[cfg["crop"]]}
    write_json(Path(cfg["output_dir"]) / "smoke_test.json", result)
    return result


class Experiment:
    def __init__(self, cfg):
        self.cfg = cfg
        self.out = Path(cfg["output_dir"])
        self.units = pd.read_csv(self.out / "environments.csv").to_dict("records")
        self.version = importlib.metadata.version("aquacrop")
        if self.version != cfg["model_version"]: raise RuntimeError("Model version mismatch")
        self.fingerprint = model_fingerprint()
        self.base = dict(crop_params[cfg["crop"]])
        self.cache = self.out / "runs"
        self.cache.mkdir(exist_ok=True)
        weather_dir = self.out / ("weather_combined" if cfg.get("cross_year") else "weather")
        self.weather = {r["Env"]: pd.read_csv(weather_dir / f"{r['Env']}.csv", parse_dates=["Date"]) for r in self.units}
        self.weather_hash = {r["Env"]: sha256_file(weather_dir / f"{r['Env']}.csv") for r in self.units}
        # Adapter source changes also invalidate all run caches.
        self.adapter_hash = sha256_file(Path(__file__))

    def run(self, unit, offset=0, scale=1.0, hi0=None, water_pct=None, root_scale=1.0, store_daily=False, force=False, planting_date=None):
        cfg = self.cfg
        hi0 = self.base["HI0"] if hi0 is None else float(hi0)
        water_pct = cfg["initial_available_water_pct"] if water_pct is None else float(water_pct)
        date = pd.Timestamp(planting_date) if planting_date is not None else pd.Timestamp(unit["planting_date"]) + pd.Timedelta(days=int(offset))
        offset = (date - pd.Timestamp(unit["planting_date"])).days
        if date.year != unit["year"]: raise ValueError("Cross-year planting not supported in quick experiment")
        control = {"unit_id": unit["unit_id"], "offset": int(offset), "scale": float(scale), "hi0": hi0,
                   "water_pct": water_pct, "root_scale": float(root_scale), "weather_sha256": self.weather_hash[unit["Env"]],
                   "model_sha256": self.fingerprint, "adapter_sha256": self.adapter_hash, "config": cfg, "unit": unit}
        key = hashlib.sha256(json.dumps(control, sort_keys=True).encode()).hexdigest()[:24]
        summary_path, daily_path = self.cache / f"{key}.json", self.cache / f"{key}.parquet"
        if summary_path.exists() and not force:
            old = json.loads(summary_path.read_text())
            if old["status"] != "execution_failed" and (not store_daily or daily_path.exists()): return old
        start = time.perf_counter()
        summary = {"run_id": key, "unit_id": unit["unit_id"], "Env": unit["Env"], "site": unit["site"], "year": unit["year"], "split": unit["split"],
                   "offset_days": int(offset), "planting_date": date.strftime("%Y-%m-%d"), "actual_planting_date": None,
                   "phenology_scale": float(scale), "HI0": hi0, "initial_available_water_pct": water_pct, "root_depth_scale": float(root_scale),
                   "model_version": self.version, "input_hash": key, "weather_sha256": self.weather_hash[unit["Env"]],
                   "status": "execution_failed", "dry_yield_Mg_ha": None, "flowering_proxy_DAP": None}
        try:
            if not cfg.get("cross_year") and date.month == 12 and date.day == 31:
                summary.update(status="calendar_not_supported", termination_reason="OSPy treats identical planting and harvest month/day as cross-year; same-year cutoff requested")
                write_json(summary_path, summary)
                return summary
            dz = [float(cfg["soil_compartment_m"])] * round(cfg["soil_depth_m"] / cfg["soil_compartment_m"])
            soil = Soil(unit["soil_type"], dz=dz)
            prof = soil.profile.copy()
            if not ((prof.th_wp < prof.th_fc) & (prof.th_fc < prof.th_s)).all(): raise ValueError("Invalid soil hydraulic ordering")
            theta_ini = prof.th_wp.to_numpy() + water_pct / 100 * (prof.th_fc - prof.th_wp).to_numpy()
            kwargs = {k: self.base[k] * scale for k in THERMAL_KEYS}
            # OSPy auto-enlarges the soil if Zmax+0.1 exceeds profile depth.
            # Reserve its required 0.1 m lower buffer explicitly so the
            # engine does not change compartment thickness during setup.
            root_cap = cfg["soil_depth_m"] - 0.1
            kwargs.update(HI0=hi0, PlantPop=cfg["plant_population_ha"], Zmax=min(min(self.base["Zmax"], root_cap) * root_scale, root_cap))
            if cfg.get("cross_year"):
                # The package accepts recurring month/day rules rather than full
                # dates. Ending one day before the next anniversary gives this
                # single season at most one year, including Dec 31 sowings.
                simulation_end = date + pd.DateOffset(years=1) - pd.Timedelta(days=1)
                # OSPy interprets recurring month/day rules using 1990, a
                # non-leap year. A Feb 29 harvest rule cannot be parsed.
                leap_rule_adjusted = simulation_end.month == 2 and simulation_end.day == 29
                if leap_rule_adjusted:
                    simulation_end -= pd.Timedelta(days=1)
                harvest_rule = simulation_end.strftime("%m/%d")
            else:
                simulation_end = pd.Timestamp(f"{unit['year']}-12-31")
                harvest_rule = "12/31"
                leap_rule_adjusted = False
            summary["simulation_end_date"] = simulation_end.strftime("%Y-%m-%d")
            summary["configured_harvest_rule"] = harvest_rule
            summary["leap_day_harvest_rule_adjusted"] = leap_rule_adjusted
            crop = Crop(cfg["crop"], date.strftime("%m/%d"), harvest_date=harvest_rule, **kwargs)
            # Do not trigger an adaptive shift of the intervention date.
            crop.PlantTrigger = None
            effective = dict(crop.__dict__)
            w = self.weather[unit["Env"]].copy(deep=True)
            # The 3.1.0 setter validates names, but the engine uses positional
            # arrays: min/max/rain/ET0/date. Date must be the fifth column.
            model_weather = w[["MinTemp", "MaxTemp", "Precipitation", "ReferenceET", "Date"]].copy()
            model_weather["ReferenceET"] = model_weather.ReferenceET.clip(lower=0.1)
            model = AquaCropModel(f"{unit['year']}/01/01", simulation_end.strftime("%Y/%m/%d"), model_weather,
                                  soil, crop, InitialWaterContent(wc_type="Pct", method="Layer", depth_layer=[1], value=[water_pct]),
                                  irrigation_management=IrrigationManagement(irrigation_method=0), off_season=True)
            model.run_model(till_termination=True)
            if not np.allclose(soil.profile.dz.to_numpy(), dz, rtol=0, atol=1e-12):
                raise ValueError("Engine changed soil geometry; root-depth buffer was insufficient")
            stats = model.get_simulation_results()
            growth, flux, storage = model.get_crop_growth().copy(), model.get_water_flux().copy(), model.get_water_storage().copy()
            # OSPy allocates output arrays for the full time span even if the
            # crop finishes early. Padding rows are not simulated observations.
            last = np.flatnonzero(growth.time_step_counter.to_numpy() > 0)
            n = int(last[-1] + 1) if len(last) else 1
            growth, flux, storage = growth.iloc[:n].copy(), flux.iloc[:n].copy(), storage.iloc[:n].copy()
            for frame in (growth, flux, storage):
                if not np.array_equal(frame.time_step_counter.to_numpy(), np.arange(n)): raise ValueError("Output time-step alignment failed")
            daily = growth.copy()
            for col in flux.columns:
                if col not in daily: daily[col] = flux[col].to_numpy()
            daily["growing_season"] = storage.growing_season.to_numpy().astype(bool)
            for col in storage.columns:
                if col.startswith("th"): daily[col] = storage[col].to_numpy()
            daily["Date"] = pd.date_range(f"{unit['year']}-01-01", periods=n)
            daily["Precipitation_mm_day"] = w.Precipitation.iloc[:n].to_numpy()
            daily["ReferenceET_mm_day"] = model_weather.ReferenceET.iloc[:n].to_numpy()
            th_cols = [f"th{i+1}" for i in range(len(dz))]
            theta = daily[th_cols].to_numpy()
            daily["soil_water_mm"] = (theta * np.asarray(dz) * 1000).sum(axis=1)
            initial_storage = float((theta_ini * np.asarray(dz) * 1000).sum())
            total_storage = daily.soil_water_mm.to_numpy() + daily.surface_storage.to_numpy()
            delta_storage = total_storage - np.r_[initial_storage, total_storage[:-1]]
            net = daily.Precipitation_mm_day + daily.IrrDay + daily.CR + daily.GwIn - daily.Runoff - daily.DeepPerc - daily.TileDrain - daily.Es - daily.Tr
            daily["water_balance_residual_mm"] = delta_storage - net.to_numpy()
            summary["water_balance_max_abs_mm_day"] = float(np.abs(daily.water_balance_residual_mm).max())
            summary["water_balance_total_residual_mm"] = float(daily.water_balance_residual_mm.sum())
            summary["soil_water_bounds_ok"] = bool((theta >= prof.th_dry.to_numpy() - 1e-6).all() and (theta <= prof.th_s.to_numpy() + 1e-6).all())
            active = daily.loc[daily.growing_season]
            if not active.empty: summary["actual_planting_date"] = active.Date.iloc[0].strftime("%Y-%m-%d")
            if summary["actual_planting_date"] != summary["planting_date"]: raise ValueError("Actual planting date differs from requested intervention")
            pre = daily.loc[daily.Date < date]
            summary["preplant_days_simulated"] = len(pre)
            summary["initial_soil_water_mm"] = initial_storage
            summary["day_before_planting_soil_water_mm"] = float(pre.soil_water_mm.iloc[-1]) if len(pre) else None
            summary["preplant_soil_water_range_mm"] = float(pre.soil_water_mm.max() - pre.soil_water_mm.min()) if len(pre) else 0.0
            # No public termination-reason API exists in 3.1.0. Keep this sole
            # pinned state bridge inside the adapter; never read private outputs.
            cond = model._init_cond
            if cond.crop_mature: status = "matured"
            elif cond.crop_dead: status = "crop_died"
            elif not cond.germination: status = "not_germinated"
            else: status = "not_matured"
            summary["status"] = status
            summary["termination_reason"] = status if status != "not_matured" else "latest_harvest_or_year_end_before_maturity"
            summary["last_simulated_date"] = daily.Date.iloc[-1].strftime("%Y-%m-%d")
            end_date = pd.Timestamp(stats["Harvest Date (YYYY/MM/DD)"].iloc[0]) if len(stats) and pd.notna(stats["Harvest Date (YYYY/MM/DD)"].iloc[0]) else daily.Date.iloc[-1] + pd.Timedelta(days=1)
            summary["termination_date"] = end_date.strftime("%Y-%m-%d")
            summary["maturity_date"] = end_date.strftime("%Y-%m-%d") if status == "matured" else None
            summary["dry_yield_Mg_ha"] = float(stats["Dry yield (tonne/ha)"].iloc[0]) if len(stats) else float(active.DryYield.iloc[-1]) if len(active) else 0.0
            summary["yield_at_15p5_Mg_ha"] = summary["dry_yield_Mg_ha"] / (1 - cfg["grain_standard_moisture_fraction"])
            summary["biomass_Mg_ha"] = float(daily.biomass.max() / 100)
            flower = active.loc[active.gdd_cum >= kwargs["HIstart"]]
            if len(flower):
                flower_date = flower.Date.iloc[0] + pd.Timedelta(days=1)
                summary["flowering_proxy_date"] = flower_date.strftime("%Y-%m-%d")
                summary["flowering_proxy_DAP"] = (flower_date - date).days
            summary["seasonal_evaporation_mm"] = float(active.Es.sum())
            summary["seasonal_transpiration_mm"] = float(active.Tr.sum())
            summary["seasonal_et_mm"] = summary["seasonal_evaporation_mm"] + summary["seasonal_transpiration_mm"]
            summary["seasonal_precipitation_mm"] = float(active.Precipitation_mm_day.sum())
            summary["seasonal_irrigation_mm"] = float(active.IrrDay.sum())
            summary["effective_max_root_depth_m"] = kwargs["Zmax"]
            summary["root_depth_clipped_by_profile"] = bool(self.base["Zmax"] * root_scale > root_cap)
            summary["max_simulated_root_depth_m"] = float(active.z_root.max()) if len(active) else 0.0
            summary["observed_harvest_before_simulated_maturity"] = bool(unit.get("observed_harvest_date") and status == "matured" and pd.Timestamp(unit["observed_harvest_date"]) < end_date)
            if not np.isfinite(summary["dry_yield_Mg_ha"]) or not summary["soil_water_bounds_ok"]: raise ValueError("Invalid yield or water bounds")
            if summary["water_balance_max_abs_mm_day"] > 1:
                daily.to_parquet(self.cache / f"{key}.diagnostic.parquet", index=False)
                raise ValueError("Water balance residual exceeds 1 mm/day; inspect adapter convention")
            if store_daily:
                daily.to_parquet(daily_path, index=False)
                prof.to_csv(self.cache / f"{key}.soil.csv", index=False)
                write_json(self.cache / f"{key}.crop.json", effective)
        except Exception:
            summary["status"] = "execution_failed"
            summary["error"] = traceback.format_exc()
            if "not enough growing degree days in simulation" in summary["error"]:
                summary["status"] = "insufficient_thermal_time"
                summary["termination_reason"] = "OSPy rejects initialization because available thermal time cannot reach configured maturity"
            elif "crop will take longer than 1 year to mature" in summary["error"]:
                summary["status"] = "exceeds_model_one_year_limit"
                summary["termination_reason"] = "OSPy 3.1.0 rejects a single season requiring 365 or more days to maturity"
        if summary["status"] == "execution_failed":
            summary["dry_yield_Mg_ha"] = None
            summary["yield_at_15p5_Mg_ha"] = None
        summary["elapsed_seconds"] = time.perf_counter() - start
        write_json(summary_path, summary)
        return summary

    def require_ok(self, result):
        if result["status"] == "execution_failed": raise RuntimeError(result["error"])
        return result
