"""Native DSSAT translation and result handling."""

from datetime import date, timedelta

from snowwindow.domain import (
    Environment,
    ManagementUnit,
    SimulationRequest,
    WeatherRecord,
)
from snowwindow.models.dssat.adapter import (
    parse_summary,
    render_cultivar,
    render_weather,
)


def test_weather_uses_dssat_two_digit_year_and_daily_units():
    start = date(2022, 1, 1)
    request = SimulationRequest(
        request_id="one",
        environment=Environment(
            environment_id="INH1_2022",
            year=2022,
            location="IN",
            latitude=40.0,
            longitude=-86.0,
            weather=tuple(
                WeatherRecord(
                    environment_id="INH1_2022",
                    date=start + timedelta(days=index),
                    values={
                        "ALLSKY_SFC_SW_DWN": 12.5,
                        "T2M_MAX": 23.0,
                        "T2M_MIN": 9.0,
                        "PRECTOTCORR": 2.0,
                    },
                )
                for index in range(2)
            ),
        ),
        management=ManagementUnit("unit", "INH1_2022", start),
        start_date=start,
        end_date=start + timedelta(days=1),
    )
    weather = render_weather(request)
    assert "@DATE  SRAD  TMAX  TMIN  RAIN" in weather
    assert "22001  12.5  23.0   9.0   2.0" in weather


def test_summary_distinguishes_maturity_from_missing_output():
    header = (
        "@"
        + "".join(
            f"{name:>8}"
            for name in (
                "RUNNO",
                "TRNO",
                "PDAT",
                "EDAT",
                "ADAT",
                "MDAT",
                "HWAM",
                "CWAM",
                "CRST",
            )
        )
        + "\n"
    )
    matured = (
        header
        + " "
        + "".join(
            f"{value:>8}"
            for value in (
                "1",
                "1",
                "2022120",
                "2022130",
                "2022180",
                "2022200",
                "5000",
                "10000",
                "1",
            )
        )
        + "\n"
    )
    result = parse_summary(matured, date(2022, 4, 30))
    assert result["maturity_date"] == "2022-07-19"
    assert result["dry_yield_mg_ha"] == 5.0
    assert result["flowering_proxy_dap"] == 60
    assert parse_summary(header, date(2022, 4, 30)) is None


def test_cultivar_tuning_only_updates_reference_row():
    reference = (
        "IB0035 McCurdy 84aa         . IB0001 259.0 1.193 947.1 "
        "924.3 8.168 43.00\n"
    )
    other = "IB0036 other                    259.0 1.193 947.1 924.3\n"
    tuned = render_cultivar(reference + other, 170.0, 790.0)
    assert "IB0001 170.0 1.193 947.1 790.0 8.168 43.00" in tuned
    assert other in tuned
