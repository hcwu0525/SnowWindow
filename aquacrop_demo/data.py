"""Read-only G2F selection and provenance-preserving weather preparation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .physics import reference_et

TEXTURES = {"Clay": "Clay", "Clay Loam": "ClayLoam", "Loam": "Loam",
            "Loamy Sand": "LoamySand", "Sand": "Sand", "Sandy Clay": "SandyClay",
            "Sandy Clay Loam": "SandyClayLoam", "Sandy Loam": "SandyLoam",
            "Silt": "Silt", "Silt Loam": "SiltLoam", "Silty Clay": "SiltClay",
            "Silty Clay Loam": "SiltClayLoam"}
SEVERE_ISSUES = re.compile(r"lodging|greensnap|goose.?neck|cranes|mixed seeds|mixed between|planter had an issue|planting mistake|busted berm|plots.*irrigated|uneven germination|extremely variable|some seed.*(?:did not|didn't)", re.I)
EXPECTED_UNITS = {"T2M_MIN": "C", "T2M_MAX": "C", "PRECTOTCORR": "mm/day", "RH2M": "%",
                  "WS2M": "m/s", "ALLSKY_SFC_SW_DWN": "MJ/m^2/day", "PS": "kPa"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    def convert(x):
        if isinstance(x, (np.integer, np.floating)): return x.item()
        if isinstance(x, np.ndarray): return x.tolist()
        if isinstance(x, (pd.Timestamp, Path)): return str(x)
        raise TypeError(type(x).__name__)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=convert), encoding="utf-8")
    temporary.replace(path)


def _coordinate(row, kind):
    # POWER weather uses station location where available. Field centroid is fallback.
    station = f"Weather_Station_{kind} (in decimal numbers NOT DMS)"
    value = pd.to_numeric(row.get(station), errors="coerce")
    if np.isfinite(value): return float(value), "weather_station"
    vals = [pd.to_numeric(v, errors="coerce") for k, v in row.items() if k.startswith(f"{kind}_of_Field_Corner_")]
    vals = [v for v in vals if np.isfinite(v)]
    return (float(np.mean(vals)), "field_centroid") if vals else (np.nan, "missing")


def select_units(cfg) -> pd.DataFrame:
    src, out = Path(cfg["data_dir"]), Path(cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    files = {"traits": src / "1_Training_Trait_Data_2014_2023.csv",
             "metadata": src / "2_Training_Meta_Data_2014_2023.csv",
             "soil": src / "3_Training_Soil_Data_2015_2023.csv",
             "weather": src / "4_Training_Weather_Data_2014_2023_full_year.csv"}
    trait_cols = ["Env", "Year", "Field_Location", "Experiment", "Hybrid", "Date_Planted", "Date_Harvested", "Pollen_DAP_days", "Silk_DAP_days", "Yield_Mg_ha"]
    t = pd.read_csv(files["traits"], usecols=trait_cols, low_memory=False)
    meta = pd.read_csv(files["metadata"], low_memory=False).fillna("")
    soil = pd.read_csv(files["soil"], low_memory=False)
    for col in ["Pollen_DAP_days", "Silk_DAP_days", "Yield_Mg_ha"]:
        t[col] = pd.to_numeric(t[col], errors="coerce")
        t.loc[t[col] < 0, col] = np.nan
    for col in ["Pollen_DAP_days", "Silk_DAP_days"]:
        t.loc[~t[col].between(1, 200), col] = np.nan
    t["planting_date"] = pd.to_datetime(t.Date_Planted, format="mixed", errors="coerce")
    t["harvest_date"] = pd.to_datetime(t.Date_Harvested, format="mixed", errors="coerce")
    rows, eligible = [], []
    for _, m in meta.iterrows():
        env = m.Env
        notes = " | ".join(str(v) for k, v in m.items() if k.startswith("Issue/") and v)
        base = {"Env": env, "irrigated": m.Irrigated, "notes": notes}
        reasons = []
        if str(m.Irrigated).strip().lower() != "no": reasons.append("rainfed_not_confirmed")
        if SEVERE_ISSUES.search(notes): reasons.append("major_nonmodelled_or_mixed_management_issue")
        samples = soil.loc[soil.Env.eq(env)]
        texture_values = samples.Texture.dropna().loc[lambda s: s.isin(TEXTURES)]
        if texture_values.empty:
            texture, soil_type = "", ""
            reasons.append("soil_texture_missing_or_ambiguous")
        else:
            texture = texture_values.value_counts().sort_index().idxmax()
            soil_type = TEXTURES[texture]
        lat, lat_src = _coordinate(m, "Latitude")
        lon, lon_src = _coordinate(m, "Longitude")
        if not np.isfinite(lat) or not np.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
            reasons.append("coordinates_invalid")
        env_traits = t.loc[t.Env.eq(env)].dropna(subset=["planting_date", "Hybrid", "Experiment"])
        env_traits = env_traits.loc[env_traits.planting_date.dt.year.eq(env_traits.Year)]
        if env_traits.empty: reasons.append("planting_or_traits_missing")
        base.update(texture=texture, soil_type=soil_type, latitude=lat, longitude=lon)
        if reasons:
            rows.append({**base, "selected": False, "reason": ";".join(reasons)})
            continue
        # Keep management units separate. Choose the largest main experiment by
        # raw plot count, not by its yield, for the fixed-size quick experiment.
        grouped = list(env_traits.groupby(["Experiment", "planting_date"]))
        grouped.sort(key=lambda pair: (-len(pair[1]), str(pair[0][0]), pair[0][1]))
        for number, ((experiment, date), g) in enumerate(grouped):
            unit_id = f"{env}__{experiment}__{date:%Y%m%d}"
            record = {**base, "unit_id": unit_id, "experiment": experiment, "planting_date": date.strftime("%Y-%m-%d"), "n_plots": len(g)}
            if number:
                rows.append({**record, "selected": False, "reason": "other_management_unit_not_in_quick_subset"})
                continue
            # Average replicate plots per hybrid, then weight each hybrid equally.
            h = g.groupby("Hybrid")[["Pollen_DAP_days", "Silk_DAP_days", "Yield_Mg_ha"]].mean()
            if h.Pollen_DAP_days.notna().sum() < 10 or h.Yield_Mg_ha.notna().sum() < 10:
                rows.append({**record, "selected": False, "reason": "insufficient_valid_observations"})
                continue
            record.update(site=str(g.Field_Location.mode().iloc[0]), year=int(g.Year.iloc[0]),
                          coordinate_source=f"{lat_src}/{lon_src}", n_hybrids=len(h),
                          n_pollen_hybrids=int(h.Pollen_DAP_days.notna().sum()), n_yield_hybrids=int(h.Yield_Mg_ha.notna().sum()),
                          observed_pollen_DAP=float(h.Pollen_DAP_days.mean()), observed_silk_DAP=float(h.Silk_DAP_days.mean()),
                          observed_yield_15p5_Mg_ha=float(h.Yield_Mg_ha.mean()),
                          observed_dry_yield_Mg_ha=float(h.Yield_Mg_ha.mean() * (1 - cfg["grain_standard_moisture_fraction"])),
                          pollen_between_hybrid_sd_days=float(h.Pollen_DAP_days.std()),
                          dry_yield_between_hybrid_sd_Mg_ha=float(h.Yield_Mg_ha.std() * (1 - cfg["grain_standard_moisture_fraction"])),
                          observed_harvest_date=g.harvest_date.median().strftime("%Y-%m-%d") if g.harvest_date.notna().any() else "",
                          soil_sample_count=len(samples), soil_texture_disagreement=texture_values.nunique() > 1)
            eligible.append(record)
    e = pd.DataFrame(eligible)
    if e.empty: raise ValueError("No fully eligible rainfed environment found")
    counts = e.groupby("site").year.nunique()
    preferred = counts[counts >= cfg["years_per_site"]]
    size_reduction = preferred.empty
    pool = counts[counts >= cfg["minimum_years_per_site"]] if size_reduction else preferred
    if pool.empty: raise ValueError("No site with two eligible years; inspect selection_audit")
    sites = sorted(pool.index, key=lambda s: (-pool[s], s))[:cfg["sites"]]
    selected = []
    for site in sites:
        g = e.loc[e.site.eq(site)].sort_values("year").tail(cfg["years_per_site"])
        for _, row in g.iterrows():
            row = row.to_dict()
            row["split"] = "test" if row["year"] == g.year.max() else "train"
            selected.append(row)
    selected_ids = {r["unit_id"] for r in selected}
    rows.extend({**r, "selected": r["unit_id"] in selected_ids,
                 "reason": "selected" if r["unit_id"] in selected_ids else "outside_selected_sites_or_years"} for r in eligible)
    pd.DataFrame(rows).to_csv(out / "selection_audit.csv", index=False)
    units = pd.DataFrame(selected).sort_values(["site", "year"]).reset_index(drop=True)
    units.to_csv(out / "environments.csv", index=False)
    write_json(out / "selection_manifest.json", {"requested_sites": cfg["sites"], "requested_years_per_site": cfg["years_per_site"],
               "actual_units": len(units), "actual_sites": sites, "years_reduced": size_reduction,
               "rainfed_flags_by_year": meta.loc[meta.Irrigated.eq("no"), "Year"].value_counts().to_dict(),
               "selection_uses_no_yield_magnitude": True, "representative_experiment_rule": "largest raw plot count; other management units retained in audit",
               "source_files": {k: {"path": str(v), "sha256": sha256_file(v)} for k, v in files.items()},
               "grain_moisture_basis": {"standard_moisture_fraction": cfg["grain_standard_moisture_fraction"], "source": cfg["sources"]["yield_moisture"]}})
    print(units[["Env", "experiment", "planting_date", "texture", "split"]].to_string(index=False), flush=True)
    return units


def _download_weather(cfg, row):
    out = Path(cfg["output_dir"])
    raw_dir = out / "weather_raw"
    raw_dir.mkdir(exist_ok=True)
    path = raw_dir / f"{row['Env']}.json"
    params = dict(parameters=",".join(cfg["weather_parameters"]), community="AG", longitude=row["longitude"], latitude=row["latitude"],
                  start=f"{row['year']}0101", end=f"{row['year']}1231", format="JSON")
    url = cfg["sources"]["weather"] + "?" + urllib.parse.urlencode(params)
    if not path.exists():
        last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=75) as response: raw = json.load(response)
                write_json(path, raw)
                break
            except Exception as err:
                last_error = err
                time.sleep(1 + attempt)
        else: raise RuntimeError(f"NASA POWER failed for {row['Env']}: {last_error}")
    raw = json.loads(path.read_text())
    for p, unit in EXPECTED_UNITS.items():
        if raw["parameters"][p]["units"] != unit:
            raise ValueError(f"Unexpected POWER unit {p}: {raw['parameters'][p]['units']}")
    w = pd.DataFrame(raw["properties"]["parameter"])
    w["Date"] = pd.to_datetime(w.index, format="%Y%m%d")
    w = w.reset_index(drop=True).sort_values("Date")
    expected = pd.date_range(f"{row['year']}-01-01", f"{row['year']}-12-31")
    if not np.array_equal(w.Date.to_numpy(), expected.to_numpy()): raise ValueError("Weather missing or duplicate days")
    if not np.isfinite(w[cfg["weather_parameters"]].to_numpy()).all() or (w[cfg["weather_parameters"]] <= -900).any().any():
        raise ValueError("NASA POWER contains missing values")
    if (w.T2M_MIN > w.T2M_MAX).any() or (w.PRECTOTCORR < 0).any() or not w.RH2M.between(0, 100).all() or (w.WS2M < 0).any():
        raise ValueError("Invalid weather bounds")
    elevation = float(raw["geometry"]["coordinates"][2])
    w = reference_et(w, row["latitude"], elevation)
    w["MinTemp"] = w.T2M_MIN
    w["MaxTemp"] = w.T2M_MAX
    w["Precipitation"] = w.PRECTOTCORR
    weather_dir = out / "weather"
    weather_dir.mkdir(exist_ok=True)
    w.to_csv(weather_dir / f"{row['Env']}.csv", index=False)
    meta = {"Env": row["Env"], "request_url": url, "raw_sha256": sha256_file(path),
            "source": "fresh NASA POWER AG data; not an exact replication of original competition weather",
            "units": raw["parameters"], "elevation_m": elevation,
            "et0_method": "FAO-56 daily PM; RHmean approximation eq19; G=0; actual pressure; negative ET0 clipped to zero",
            "negative_et0_clipped_days": int((w.ET0_unclipped_mm_day < 0).sum()),
            "ET0_min_mm_day": float(w.ReferenceET.min()), "ET0_max_mm_day": float(w.ReferenceET.max())}
    write_json(raw_dir / f"{row['Env']}.provenance.json", meta)
    print(f"Weather ready {row['Env']}: {len(w)} days, ET0 {w.ReferenceET.min():.2f}–{w.ReferenceET.max():.2f} mm/day", flush=True)
    return meta


def prepare(cfg):
    units = select_units(cfg)
    with ThreadPoolExecutor(max_workers=3) as pool:
        provenance = list(pool.map(lambda row: _download_weather(cfg, row), units.to_dict("records")))
    write_json(Path(cfg["output_dir"]) / "weather_manifest.json", provenance)
    # Compare source columns, but don't infer units from numerical similarity.
    local = pd.read_csv(Path(cfg["data_dir"]) / "4_Training_Weather_Data_2014_2023_full_year.csv")
    local["Date"] = pd.to_datetime(local.Date.astype(str), format="%Y%m%d")
    comparisons = []
    for env in units.Env.unique():
        w = pd.read_csv(Path(cfg["output_dir"]) / "weather" / f"{env}.csv", parse_dates=["Date"])
        joined = w.merge(local.loc[local.Env.eq(env)], on="Date", suffixes=("_refresh", "_local"))
        for col in cfg["weather_parameters"]:
            a = joined[f"{col}_refresh"].to_numpy()
            b = pd.to_numeric(joined[f"{col}_local"], errors="coerce").to_numpy()
            mask = np.isfinite(a) & np.isfinite(b) & (b > -900)
            comparisons.append({"Env": env, "variable": col, "matched_days": int(mask.sum()),
                                "rmse_raw_values": float(np.sqrt(np.mean((a[mask] - b[mask]) ** 2))) if mask.any() else None,
                                "note": "original unit metadata unavailable; comparison does not validate original units"})
    pd.DataFrame(comparisons).to_csv(Path(cfg["output_dir"]) / "original_vs_refreshed_weather.csv", index=False)
    return units
