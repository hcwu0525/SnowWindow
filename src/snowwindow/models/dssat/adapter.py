"""Generate isolated DSSAT maize inputs and read native DSSAT outputs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import date
from functools import cached_property
from pathlib import Path

from snowwindow.domain import (
    CalibrationParameter,
    FoldStrategy,
    ModelCapabilities,
    RunStatus,
    ScanRequestStrategy,
    SimulationRequest,
    SimulationResult,
    WeatherStrategy,
)

VERSION = "4.8.6.2"
SOIL_ID = "IB00000007"  # DSSAT reference deep sandy loam, not a G2F measurement.
CULTIVAR = "IB0035"  # Reference McCurdy 84aa; G2F genotype is not identified.
P1_DEFAULT = 259.0
G2_DEFAULT = 924.3
WEATHER_FIELDS = ("ALLSKY_SFC_SW_DWN", "T2M_MAX", "T2M_MIN", "PRECTOTCORR")


class DSSATValidationError(ValueError):
    """Inputs cannot be simulated with the supported DSSAT reference scenario."""


def _date_code(value: date) -> str:
    return f"{value.year % 100:02d}{value.timetuple().tm_yday:03d}"


def render_weather(request: SimulationRequest) -> str:
    records = sorted(request.environment.weather, key=lambda record: record.date)
    temperatures = [
        (float(row.values["T2M_MAX"]) + float(row.values["T2M_MIN"])) / 2
        for row in records
    ]
    tav = sum(temperatures) / len(temperatures)
    amp = max(temperatures) - min(temperatures)
    rows = [
        f"{_date_code(row.date)} "
        + " ".join(f"{float(row.values[key]):5.1f}" for key in WEATHER_FIELDS)
        for row in records
    ]
    return "\n".join(
        [
            "*WEATHER DATA : G2F normalized daily weather; POWER source",
            "@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT",
            f"  G2FW {request.environment.latitude:8.3f} "
            f"{request.environment.longitude:8.3f} "
            f"{float(request.environment.metadata.get('elevation_m', 0)):5.0f}"
            f" {tav:5.1f} {amp:5.1f}  2.00  3.00",
            "@DATE  SRAD  TMAX  TMIN  RAIN",
            *rows,
            "",
        ]
    )


def parse_summary(text: str, planting_date: date) -> dict[str, object] | None:
    """Parse DSSAT's column-aligned Summary.OUT without confusing -99 with maturity."""
    lines = text.splitlines()
    header = next((line for line in lines if line.startswith("@   RUNNO")), None)
    if header is None:
        return None
    row = next(
        (line for line in lines if re.match(r"^\s+1\s+1\s+", line)),
        None,
    )
    if row is None:
        return None
    fields = list(re.finditer(r"\S+", header))
    values = {
        field.group(): row[
            fields[index - 1].end() if index else 0 : field.end()
        ].strip()
        for index, field in enumerate(fields)
    }

    def julian(key: str) -> date | None:
        value = values.get(key, "-99")
        if not re.fullmatch(r"\d{7}", value):
            return None
        try:
            return date.fromordinal(
                date(int(value[:4]), 1, 1).toordinal() + int(value[4:]) - 1
            )
        except ValueError:
            return None

    def amount(key: str) -> float | None:
        try:
            number = float(values.get(key, "-99"))
        except ValueError:
            return None
        return number if math.isfinite(number) and number >= 0 else None

    flowering = julian("ADAT")
    maturity = julian("MDAT")
    yield_kg = amount("HWAM")
    biomass_kg = amount("CWAM")
    return {
        "flowering_date": flowering.isoformat() if flowering else None,
        "flowering_proxy_dap": (
            (flowering - planting_date).days if flowering else None
        ),
        "maturity_date": maturity.isoformat() if maturity else None,
        "dry_yield_mg_ha": yield_kg / 1000
        if maturity and yield_kg is not None
        else None,
        "biomass_mg_ha": biomass_kg / 1000 if biomass_kg is not None else None,
    }


def render_experiment(template: str, request: SimulationRequest) -> str:
    """Retain official experiment layout with explicitly fixed reference assumptions."""
    sowing = request.management.planting_date
    start = request.start_date
    end = request.end_date
    if not start <= sowing <= end:
        raise DSSATValidationError("planting date must be within simulation interval")
    planted = _date_code(sowing)
    simulation_start = _date_code(start)
    harvest_end = _date_code(end)
    population = request.management.population_plants_m2 or 7.5
    if not 1 <= population <= 20:
        raise DSSATValidationError("plant density must be in [1, 20] plants/m2")

    # Replace whole sections so no Gainesville weather, soil, planting or
    # irrigation events silently leak into G2F simulations.
    replacements = {
        "*FIELDS": (
            "*FIELDS\n"
            "@L ID_FIELD WSTA....  FLSA  FLOB  FLDT  FLDD  FLDS  FLST"
            " SLTX  SLDP  ID_SOIL    FLNAME\n"
            f" 1 G2F00001 G2FW       -99     0 DR000     0     0 00000"
            f" -99    210  {SOIL_ID} Reference\n"
            "@L ...........XCRD ...........YCRD .....ELEV .............AREA"
            " .SLEN .FLWR .SLAS FLHST FHDUR\n"
            f" 1 {request.environment.latitude:15.4f} "
            f"{request.environment.longitude:15.4f} "
            f"{float(request.environment.metadata.get('elevation_m', 0)):9.0f}"
            "                 0     0     0     0   -99   -99\n\n"
        ),
        "*INITIAL CONDITIONS": (
            "*INITIAL CONDITIONS\n"
            "@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD"
            " ICRES ICREN ICREP ICRIP ICRID ICNAME\n"
            f" 1    MZ {simulation_start}   100     0     1     1"
            "   -99     0     0     0     0     0 -99\n"
            "@C  ICBL  SH2O  SNH4  SNO3\n"
            + "".join(
                f" 1 {depth:5d}   -99   1.0   5.0\n"
                for depth in (5, 15, 30, 45, 60, 90, 120, 150, 180, 210)
            )
            + "\n"
        ),
        "*PLANTING DETAILS": (
            "*PLANTING DETAILS\n"
            "@P PDATE EDATE  PPOP  PPOE  PLME  PLDS  PLRS  PLRD  PLDP"
            "  PLWT  PAGE  PENV  PLPH  SPRL                        PLNAME\n"
            f" 1 {planted}   -99 {population:5.1f} {population:5.1f}"
            "     S     R    75     0     5   -99   -99   -99"
            "   -99     0                        -99\n\n"
        ),
        "*IRRIGATION AND WATER MANAGEMENT": (
            "*IRRIGATION AND WATER MANAGEMENT\n"
            "@I  EFIR  IDEP  ITHR  IEPT  IOFF  IAME  IAMT IRNAME\n"
            " 1     1   -99   -99   -99   -99   -99   -99 -99\n\n"
        ),
        "*FERTILIZERS (INORGANIC)": (
            "*FERTILIZERS (INORGANIC)\n"
            "@F FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME\n"
            f" 1 {planted} FE001 AP001    10   120"
            "     0     0     0     0   -99 -99\n\n"
        ),
    }
    sections = re.split(r"(?=^\*[A-Z][^\n]*\n)", template, flags=re.MULTILINE)
    result = []
    for section in sections:
        key = next((name for name in replacements if section.startswith(name)), None)
        result.append(replacements[key] if key else section)
    text = "".join(result)
    text = re.sub(
        r"^ 1 MZ IB0035 .*$", " 1 MZ IB0035 Reference maize", text, flags=re.MULTILINE
    )
    # Soil/water remains active; irrigation is off; fixed nitrogen input is explicit.
    text = text.replace(
        " 1 MA              R     R     R     N     M",
        " 1 MA              R     N     R     N     M",
    )
    text = re.sub(
        r"(?m)^ 1 GE.*$",
        lambda match: match.group().replace("82056", simulation_start),
        text,
    )
    text = re.sub(
        r"(?m)^ 1 HA.*$",
        lambda match: re.sub(r"\b83057\b", harvest_end, match.group()),
        text,
    )
    text = re.sub(
        r"(?m)^ 1 PL.*$",
        lambda match: match.group().replace("82050", planted).replace("82064", planted),
        text,
    )
    # Set all treatment references to a single fully defined reference treatment.
    text = re.sub(r"(?m)^ [2-6] [1-6] 0 0 .*\n", "", text)
    text = text.replace(
        " 1 1 0 0 RAINFED LOW NITROGEN       1  1  0  1  1  1  1",
        " 1 1 0 0 G2F REFERENCE RAINFED      1  1  0  1  1  1  1",
    )
    return text.rstrip("\x1a\n") + "\n"


def render_cultivar(template: str, p1: float, g2: float) -> str:
    original = next(
        line for line in template.splitlines() if line.startswith("IB0035 ")
    )
    pattern = r"(?<=IB0001)\s+259\.0\s+1\.193\s+947\.1\s+924\.3"
    if re.search(pattern, original) is None:
        raise DSSATValidationError("official IB0035 cultivar format changed")
    updated = re.sub(
        pattern,
        f" {p1:5.1f} 1.193 947.1 {g2:5.1f}",
        original,
        count=1,
    )
    return template.replace(original, updated, 1)


class DSSATAdapter:
    name = "dssat"
    version = VERSION
    capabilities = ModelCapabilities(
        display_name="DSSAT",
        phenology_parameter=CalibrationParameter(
            "P1", P1_DEFAULT, (150.0, 350.0, 50.0), 10.0
        ),
        yield_parameter=CalibrationParameter(
            "G2", G2_DEFAULT, (700.0, 950.0, 50.0), 10.0
        ),
        supported_folds=(FoldStrategy.HELD_YEAR,),
        weather_strategy=WeatherStrategy.LEGACY_CROSSYEAR,
        scan_request_strategy=ScanRequestStrategy.SLICE_WEATHER_HORIZON,
        report_notes=(
            "- 开花日期采用 DSSAT CERES-Maize 输出的 ADAT 开花日，"
            "与 G2F 花粉日期作代理比较。",
            "- 土壤 IB00000007、IB0035 品种、120 kg N/ha 播期施用和雨养"
            "均为固定参考情景，并非实测管理。",
            "- 全局校准仅拟合 P1 与 G2（2022）；2023 保留用于留年评估。",
        ),
    )

    def __init__(self, installation: Path | None = None) -> None:
        self.installation = (
            installation
            or (Path(__file__).resolve().parents[4] / ".tools/dssat/4.8.6.2")
        ).resolve()
        self.executable = self.installation / "dscsm048"

    @cached_property
    def source_fingerprints(self) -> dict[str, str]:
        paths = {
            "adapter_source_sha256": Path(__file__),
            "dssat_executable_sha256": self.executable,
            "dssat_experiment_template_sha256": self.installation
            / "Maize/UFGA8201.MZX",
            "dssat_cultivar_source_sha256": self.installation / "Genotype/MZCER048.CUL",
            "dssat_ecotype_source_sha256": self.installation / "Genotype/MZCER048.ECO",
            "dssat_species_source_sha256": self.installation / "Genotype/MZCER048.SPE",
            "dssat_soil_source_sha256": self.installation / "Soil/SOIL.SOL",
            "dssat_profile_source_sha256": self.installation / "DSSATPRO.L48",
        }
        return {
            key: hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in paths.items()
        }

    def validate(self, request: SimulationRequest) -> None:
        for relative in (
            "dscsm048",
            "DSSATPRO.L48",
            "Maize/UFGA8201.MZX",
            "Genotype/MZCER048.CUL",
            "Genotype/MZCER048.ECO",
            "Genotype/MZCER048.SPE",
            "Soil/SOIL.SOL",
        ):
            if not (self.installation / relative).is_file():
                raise DSSATValidationError(f"DSSAT file is missing: {relative}")
        if request.environment.environment_id != request.management.environment_id:
            raise DSSATValidationError("management environment does not match weather")
        if request.model_parameters.get("model_version", VERSION) != VERSION:
            raise DSSATValidationError(f"requires DSSAT {VERSION}")
        if str(request.model_parameters.get("cultivar", CULTIVAR)) != CULTIVAR:
            raise DSSATValidationError(f"supported reference cultivar is {CULTIVAR}")
        for name, default, lo, hi in (
            ("P1", P1_DEFAULT, 50, 450),
            ("G2", G2_DEFAULT, 200, 990),
        ):
            value = float(request.model_parameters.get(name, default))
            if not math.isfinite(value) or not lo <= value <= hi:
                raise DSSATValidationError(f"{name} must be in [{lo}, {hi}]")
        dates = [row.date for row in request.environment.weather]
        expected = [
            date.fromordinal(request.start_date.toordinal() + i)
            for i in range((request.end_date - request.start_date).days + 1)
        ]
        if dates != expected:
            raise DSSATValidationError(
                "exactly one weather row required per calendar day"
            )
        if not 2000 <= request.start_date.year <= 2048 or request.end_date.year > 2048:
            raise DSSATValidationError(
                "supported DSSAT weather year range is 2000-2048"
            )
        for row in request.environment.weather:
            try:
                solar, high, low, rain = (
                    float(row.values[key]) for key in WEATHER_FIELDS
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise DSSATValidationError("required daily weather is missing") from exc
            if not all(map(math.isfinite, (solar, high, low, rain))) or (
                solar < 0 or rain < 0 or low > high
            ):
                raise DSSATValidationError("daily weather is physically invalid")
        if request.output_dir is None:
            raise DSSATValidationError("DSSAT requests require output_dir")

    def cache_key(self, request: SimulationRequest) -> str:
        self.validate(request)
        payload = {
            "request": request.content_hash(),
            "sources": self.source_fingerprints,
            "reference_soil": SOIL_ID,
            "reference_cultivar": CULTIVAR,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def run(self, request: SimulationRequest) -> SimulationResult:
        key = self.cache_key(request)
        directory = Path(request.output_dir) / "dssat" / key
        directory.mkdir(parents=True, exist_ok=True)
        saved = directory / "result.json"
        if saved.is_file():
            payload = json.loads(saved.read_text(encoding="utf-8"))
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus(payload["status"]),
                summary=payload["summary"],
                failure_reason=payload["failure_reason"],
                diagnostics={"cache_key": key},
                artifacts={"run_dir": directory},
            )
        source = self.installation
        (directory / "G2F.WTH").write_text(render_weather(request), encoding="ascii")
        for year in range(request.start_date.year, request.end_date.year + 1):
            (directory / f"G2FW{year % 100:02d}01.WTH").symlink_to("G2F.WTH")
        (directory / "G2F.MZX").write_text(
            render_experiment(
                (source / "Maize/UFGA8201.MZX").read_text(encoding="latin1"), request
            ),
            encoding="ascii",
        )
        (directory / "MZCER048.CUL").write_text(
            render_cultivar(
                (source / "Genotype/MZCER048.CUL").read_text(encoding="latin1"),
                float(request.model_parameters.get("P1", P1_DEFAULT)),
                float(request.model_parameters.get("G2", G2_DEFAULT)),
            ),
            encoding="latin1",
        )
        for target, origin in (
            ("MZCER048.ECO", "Genotype/MZCER048.ECO"),
            ("MZCER048.SPE", "Genotype/MZCER048.SPE"),
            ("SOIL.SOL", "Soil/SOIL.SOL"),
        ):
            (directory / target).symlink_to(source / origin)
        # DSSAT searches CWD first. The local profile retains the short
        # installation paths required by legacy fixed-width Fortran reads.
        (directory / "DSSATPRO.L48").write_bytes((source / "DSSATPRO.L48").read_bytes())
        try:
            process = subprocess.run(
                [str(self.executable), "C", "G2F.MZX", "1"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=120,
                input="\n",
            )
            (directory / "stdout.log").write_text(
                process.stdout + process.stderr, encoding="utf-8"
            )
            error = directory / "ERROR.OUT"
            failure = (
                error.read_text(encoding="latin1", errors="replace")
                if error.exists()
                else None
            )
            summary_path = directory / "Summary.OUT"
            parsed = (
                parse_summary(
                    summary_path.read_text(encoding="latin1"),
                    request.management.planting_date,
                )
                if summary_path.exists() and failure is None
                else None
            )
            if failure or process.returncode or parsed is None:
                status = RunStatus.EXECUTION_FAILED
                reason = (
                    failure or process.stderr or process.stdout or "Summary.OUT missing"
                )[-1200:]
            elif parsed["maturity_date"] is None:
                status = RunStatus.NOT_MATURED
                reason = "DSSAT reported no physiological maturity"
            else:
                status = RunStatus.MATURED
                reason = None
        except (OSError, subprocess.TimeoutExpired) as exc:
            parsed = None
            status = RunStatus.EXECUTION_FAILED
            reason = str(exc)
        result = {
            "status": status.value,
            "failure_reason": reason,
            "summary": {
                "planting_date": request.management.planting_date.isoformat(),
                "reference_soil_id": SOIL_ID,
                "reference_cultivar_id": CULTIVAR,
                "P1": float(request.model_parameters.get("P1", P1_DEFAULT)),
                "G2": float(request.model_parameters.get("G2", G2_DEFAULT)),
                **(
                    parsed
                    or {
                        "flowering_date": None,
                        "flowering_proxy_dap": None,
                        "maturity_date": None,
                        "dry_yield_mg_ha": None,
                        "biomass_mg_ha": None,
                    }
                ),
            },
        }
        saved.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return SimulationResult(
            request_id=request.request_id,
            adapter_name=self.name,
            adapter_version=self.version,
            status=status,
            summary=result["summary"],
            failure_reason=reason,
            diagnostics={"cache_key": key},
            artifacts={"run_dir": directory},
        )
