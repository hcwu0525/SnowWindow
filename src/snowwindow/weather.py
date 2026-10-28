"""Shared G2F forcing policy; no external weather download or cache fallback."""

from datetime import date

G2F_END_DATE = date(2024, 11, 10)
WEATHER_POLICY = {
    "source": "g2f_full_year",
    "end_date": G2F_END_DATE.isoformat(),
    "continuation": "explicit_g2f_environment_mapping",
}


def weather_end_for_year(year: int) -> date:
    """Return the inclusive end of the supported weather period in a year."""

    if year > G2F_END_DATE.year:
        raise ValueError(f"G2F weather ends on {G2F_END_DATE}; unsupported year {year}")
    return min(date(year, 12, 31), G2F_END_DATE)
