"""Weather calculations used by the AquaCrop adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd


def reference_et(
    weather: pd.DataFrame, *, latitude_deg: float, elevation_m: float
) -> pd.DataFrame:
    """Compute daily FAO-56 Penman-Monteith ET0 from normalized weather."""

    result = weather.copy(deep=True)
    dates = pd.to_datetime(result["date"])
    tmin = result["T2M_MIN"].to_numpy(dtype=float)
    tmax = result["T2M_MAX"].to_numpy(dtype=float)
    tmean = (tmin + tmax) / 2
    es_min = 0.6108 * np.exp(17.27 * tmin / (tmin + 237.3))
    es_max = 0.6108 * np.exp(17.27 * tmax / (tmax + 237.3))
    es = (es_min + es_max) / 2
    ea = es * result["RH2M"].to_numpy(dtype=float) / 100
    delta = (
        4098 * (0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))) / (tmean + 237.3) ** 2
    )
    gamma = 0.000665 * result["PS"].to_numpy(dtype=float)
    day_of_year = dates.dt.dayofyear.to_numpy()
    latitude = np.deg2rad(latitude_deg)
    inverse_distance = 1 + 0.033 * np.cos(2 * np.pi * day_of_year / 365)
    declination = 0.409 * np.sin(2 * np.pi * day_of_year / 365 - 1.39)
    sunset_angle = np.arccos(np.clip(-np.tan(latitude) * np.tan(declination), -1, 1))
    extraterrestrial_radiation = (
        (24 * 60 / np.pi)
        * 0.0820
        * inverse_distance
        * (
            sunset_angle * np.sin(latitude) * np.sin(declination)
            + np.cos(latitude) * np.cos(declination) * np.sin(sunset_angle)
        )
    )
    clear_sky_radiation = (0.75 + 2e-5 * elevation_m) * extraterrestrial_radiation
    solar_radiation = result["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=float)
    radiation_ratio = np.clip(
        solar_radiation / np.maximum(clear_sky_radiation, 1e-9), 0.3, 1.0
    )
    net_longwave = (
        4.903e-9
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
        / 2
        * (0.34 - 0.14 * np.sqrt(ea))
        * (1.35 * radiation_ratio - 0.35)
    )
    net_radiation = 0.77 * solar_radiation - net_longwave
    wind_speed = result["WS2M"].to_numpy(dtype=float)
    et0 = (
        0.408 * delta * net_radiation
        + gamma * 900 / (tmean + 273) * wind_speed * (es - ea)
    ) / (delta + gamma * (1 + 0.34 * wind_speed))
    result["ET0_unclipped_mm_day"] = et0
    result["ReferenceET"] = np.maximum(et0, 0.1)
    result["Ra_MJ_m2_day"] = extraterrestrial_radiation
    result["Rn_MJ_m2_day"] = net_radiation
    result["ActualVapourPressure_kPa"] = ea
    return result
