"""Transparent daily FAO-56 reference ET and discrete date windows."""
from __future__ import annotations

import numpy as np
import pandas as pd


def reference_et(weather: pd.DataFrame, latitude_deg: float, elevation_m: float) -> pd.DataFrame:
    """Daily FAO-56 PM, G=0, RHmean fallback (FAO-56 eq.19), 2 m wind.

    Input units: °C, %, m/s, MJ/m²/day, kPa. Negative winter ET0 is
    clipped to zero. RHmean-derived vapour pressure is an approximation.
    """
    w = weather.copy()
    dates = pd.to_datetime(w["Date"])
    tmin, tmax = w.T2M_MIN.to_numpy(), w.T2M_MAX.to_numpy()
    tmean = (tmin + tmax) / 2
    es_min = 0.6108 * np.exp(17.27 * tmin / (tmin + 237.3))
    es_max = 0.6108 * np.exp(17.27 * tmax / (tmax + 237.3))
    es = (es_min + es_max) / 2
    ea = es * w.RH2M.to_numpy() / 100
    delta = 4098 * (0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))) / (tmean + 237.3) ** 2
    gamma = 0.000665 * w.PS.to_numpy()
    j = dates.dt.dayofyear.to_numpy()
    phi = np.deg2rad(latitude_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    dec = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    ra = (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rs = w.ALLSKY_SFC_SW_DWN.to_numpy()
    # FAO-56 restricts the Rs/Rso ratio to <=1; the lower bound avoids
    # a negative cloudiness correction on very dark days.
    ratio = np.clip(rs / np.maximum(rso, 1e-9), 0.3, 1.0)
    rnl = 4.903e-9 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    rn = 0.77 * rs - rnl
    u2 = w.WS2M.to_numpy()
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    w["ET0_unclipped_mm_day"] = et0
    w["ReferenceET"] = np.maximum(et0, 0)
    w["Ra_MJ_m2_day"] = ra
    w["Rn_MJ_m2_day"] = rn
    w["ActualVapourPressure_kPa"] = ea
    return w


def planting_windows(frame: pd.DataFrame, fractions=(0.9, 0.95), step_days=5) -> list[dict]:
    """Only mature scenarios; retain ties, disjoint segments and edge peaks."""
    valid = frame.loc[frame.status.eq("matured") & np.isfinite(frame.dry_yield_Mg_ha)].sort_values("offset_days")
    if valid.empty or valid.dry_yield_Mg_ha.max() <= 0:
        return [{"fraction": float(f), "status": "no_positive_mature_yield", "dates": [], "segments": []} for f in fractions]
    ymax = float(valid.dry_yield_Mg_ha.max())
    peaks = valid.loc[np.isclose(valid.dry_yield_Mg_ha, ymax, rtol=1e-9, atol=1e-9)]
    edge = bool(peaks.offset_days.isin([frame.offset_days.min(), frame.offset_days.max()]).any())
    excluded = frame.loc[~frame.status.eq("matured"), "offset_days"].astype(int).tolist()
    maturity_edge = bool(any((int(d) - step_days in excluded) or (int(d) + step_days in excluded) for d in peaks.offset_days))
    result = []
    for f in fractions:
        dates = pd.to_datetime(valid.loc[valid.dry_yield_Mg_ha >= f * ymax, "planting_date"]).sort_values().tolist()
        segments = []
        for d in dates:
            if not segments or (d - pd.Timestamp(segments[-1][1])).days != step_days:
                segments.append([d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")])
            else:
                segments[-1][1] = d.strftime("%Y-%m-%d")
        result.append({"fraction": float(f), "status": "ok", "max_dry_yield_Mg_ha": ymax,
                       "best_dates": peaks.planting_date.tolist(), "edge_peak": edge,
                       "adjacent_abnormal_candidate": maturity_edge, "excluded_candidate_offsets_days": excluded,
                       "dates": [d.strftime("%Y-%m-%d") for d in dates], "segments": segments})
    return result
