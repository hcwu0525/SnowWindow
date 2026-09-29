"""Native APSIM Next Generation adapter for the minimal G2F workflow."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.domain import RunStatus, SimulationRequest, SimulationResult

ADAPTER_NAME = "apsim"
MODEL_VERSION = "2026.9.8116.0"
REQUIRED_WEATHER = (
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "ALLSKY_SFC_SW_DWN",
)


class APSIMValidationError(ValueError):
    """A request cannot be represented by the supported APSIM workflow."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _find_model(node: dict[str, Any], name: str) -> dict[str, Any]:
    if node.get("Name") == name:
        return node
    for child in node.get("Children", []):
        try:
            return _find_model(child, name)
        except KeyError:
            continue
    raise KeyError(name)


@lru_cache(maxsize=2)
def _expanded_maize(template_path: str) -> dict[str, Any]:
    """Extract the embedded maize resource distributed with Models.dll."""

    models_dll = Path(template_path).resolve().parent.parent / "bin/Models.dll"
    payload = models_dll.read_bytes()
    marker = b'"PlantType": "Maize"'
    marker_offset = payload.find(marker)
    start = payload.rfind(
        b'{\n  "$type": "Models.Core.Simulations, Models"',
        0,
        marker_offset,
    )
    if marker_offset < 0 or start < 0:
        raise APSIMValidationError("cannot locate embedded APSIM maize resource")
    resource, _ = json.JSONDecoder().raw_decode(
        payload[start:].decode("utf-8", errors="replace")
    )
    return copy.deepcopy(_find_model(resource, "Maize"))


def _replace_named_model(
    node: dict[str, Any], name: str, replacement: dict[str, Any]
) -> bool:
    children = node.get("Children", [])
    for index, child in enumerate(children):
        if child.get("Name") == name:
            children[index] = replacement
            return True
        if _replace_named_model(child, name, replacement):
            return True
    return False


def _replace_command(commands: list[str], path: str, value: float) -> None:
    prefix = f"{path} ="
    replacement = f"{path} = {value:g}"
    for index, command in enumerate(commands):
        if command.strip().startswith(prefix):
            commands[index] = replacement
            return
    commands.append(replacement)


def render_met(request: SimulationRequest) -> str:
    """Render G2F daily weather in APSIM met format."""

    rows = []
    mean_temperatures = []
    for record in sorted(request.environment.weather, key=lambda item: item.date):
        values = record.values
        mint = float(values["T2M_MIN"])
        maxt = float(values["T2M_MAX"])
        mean_temperatures.append((mint + maxt) / 2)
        rows.append(
            f"{record.date.year} {record.date.timetuple().tm_yday} "
            f"{float(values['ALLSKY_SFC_SW_DWN']):.3f} {maxt:.3f} "
            f"{mint:.3f} {float(values['PRECTOTCORR']):.3f}"
        )
    tav = sum(mean_temperatures) / len(mean_temperatures)
    amp = max(mean_temperatures) - min(mean_temperatures)
    return "\n".join(
        [
            "[weather.met.weather]",
            f"latitude = {request.environment.latitude:g}",
            f"longitude = {request.environment.longitude:g}",
            f"tav = {tav:.3f}",
            f"amp = {amp:.3f}",
            "year day radn maxt mint rain",
            "() () (MJ/m^2/day) (oC) (oC) (mm)",
            *rows,
            "",
        ]
    )


def render_met_batch(requests: Iterable[SimulationRequest]) -> str:
    """Render one weather file from compatible request-specific subsets."""

    ordered = tuple(requests)
    if not ordered:
        raise APSIMValidationError("cannot render an empty APSIM weather batch")
    records_by_date = {}
    for request in ordered:
        for record in request.environment.weather:
            existing = records_by_date.get(record.date)
            if existing is not None and any(
                float(existing.values[name]) != float(record.values[name])
                for name in REQUIRED_WEATHER
            ):
                raise APSIMValidationError(
                    f"conflicting weather values for {record.date}"
                )
            records_by_date[record.date] = record
    environment = replace(
        ordered[0].environment,
        weather=tuple(records_by_date[key] for key in sorted(records_by_date)),
    )
    return render_met(replace(ordered[0], environment=environment))


def _sowing_code(request: SimulationRequest) -> list[str]:
    sowing = request.management.planting_date
    population = request.management.population_plants_m2 or 7.5
    return [
        "using Models.Core;",
        "using Models.PMF;",
        "using System;",
        "namespace Models {",
        " [Serializable] public class Script : Model {",
        "  [Link] private Clock Clock;",
        "  [Link] private IPlant Maize;",
        '  [EventSubscribe("DoManagement")]',
        "  private void OnDoManagement(object sender, EventArgs e) {",
        f"   if (Clock.Today == new DateTime({sowing.year}, {sowing.month}, "
        f"{sowing.day}) && !Maize.IsAlive)",
        f'    Maize.Sow(population: {population:g}, cultivar: "Dekalb_XL82", '
        "depth: 30.0, rowSpacing: 750.0);",
        "  }",
        " }",
        "}",
    ]


def build_apsim_document(
    template_path: Path,
    requests: Iterable[SimulationRequest],
    *,
    weather_filename: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Clone the official maize simulation once per request."""

    template = json.loads(Path(template_path).read_text(encoding="utf-8"))
    source_simulation = next(
        child
        for child in template["Children"]
        if child.get("$type", "").startswith("Models.Core.Simulation,")
    )
    datastore = next(
        child
        for child in template["Children"]
        if child.get("$type", "").startswith("Models.Storage.DataStore,")
    )
    ordered_requests = tuple(requests)
    if not ordered_requests:
        raise APSIMValidationError("APSIM document requires at least one request")
    parameter_pairs = {
        (
            float(request.model_parameters.get("juvenile_tt", 211.0)),
            float(request.model_parameters.get("grain_number_scale", 1.0)),
        )
        for request in ordered_requests
    }
    if len(parameter_pairs) != 1:
        raise APSIMValidationError(
            "one APSIM batch must share cultivar parameters"
        )
    juvenile_tt, grain_scale = next(iter(parameter_pairs))
    maize_replacement = copy.deepcopy(_expanded_maize(str(template_path)))
    cultivar_folder = _find_model(maize_replacement, "CultivarFolder")
    cultivar = next(
        child
        for child in cultivar_folder["Children"]
        if child.get("Name") == "Dekalb_XL82"
    )
    _replace_command(
        cultivar["Command"],
        "[Phenology].Juvenile.Target.FixedValue",
        juvenile_tt,
    )
    _replace_command(
        cultivar["Command"],
        "[Grain].MaximumGrainsPerCob.PotentialMaximumGrainsPerCob.FixedValue",
        550.0 * grain_scale,
    )
    replacements = {
        "$type": "Models.Core.Folder, Models",
        "Name": "Replacements",
        "ResourceName": None,
        "Children": [maize_replacement],
        "Enabled": True,
        "ReadOnly": False,
    }
    simulations = []
    simulation_names: dict[str, str] = {}
    for index, request in enumerate(ordered_requests):
        simulation = copy.deepcopy(source_simulation)
        simulation_name = f"sim_{index:04d}"
        simulation["Name"] = simulation_name
        simulation_names[simulation_name] = request.request_id

        clock = _find_model(simulation, "Clock")
        clock["Start"] = f"{request.start_date.isoformat()}T00:00:00"
        clock["End"] = f"{request.end_date.isoformat()}T00:00:00"
        _find_model(simulation, "Weather")["FileName"] = weather_filename

        manager = _find_model(simulation, "Sow using a variable rule")
        manager["CodeArray"] = _sowing_code(request)

        report = _find_model(simulation, "Report")
        report["VariableNames"] = [
            "[Clock].Today",
            "[Maize].Phenology.CurrentStageName",
            "[Maize].Phenology.FloweringDAS as FloweringDAS",
            "[Maize].Phenology.MaturityDAS as MaturityDAS",
            "[Maize].Grain.Total.Wt*10 as YieldKgHa",
            "[Maize].AboveGround.Wt*10 as BiomassKgHa",
        ]
        report["EventNames"] = ["[Maize].Harvesting"]
        simulations.append(simulation)

    document = copy.deepcopy(template)
    document["Children"] = [replacements, *simulations, copy.deepcopy(datastore)]
    return document, simulation_names


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_report(
    report: pd.DataFrame,
    requests_by_simulation: dict[str, SimulationRequest],
    *,
    adapter_version: str,
) -> dict[str, SimulationResult]:
    """Convert APSIM daily report rows to model-independent results."""

    results: dict[str, SimulationResult] = {}
    for simulation_name, request in requests_by_simulation.items():
        group = report.loc[report["SimulationName"].eq(simulation_name)].copy()
        if group.empty:
            results[request.request_id] = SimulationResult(
                request_id=request.request_id,
                adapter_name=ADAPTER_NAME,
                adapter_version=adapter_version,
                status=RunStatus.NOT_MATURED,
                summary={
                    "planting_date": request.management.planting_date.isoformat(),
                    "flowering_proxy_dap": None,
                    "flowering_date": None,
                    "maturity_date": None,
                    "dry_yield_mg_ha": None,
                    "biomass_mg_ha": None,
                    "juvenile_tt": float(
                        request.model_parameters.get("juvenile_tt", 211.0)
                    ),
                    "grain_number_scale": float(
                        request.model_parameters.get("grain_number_scale", 1.0)
                    ),
                },
                failure_reason="no harvest event before simulation end",
            )
            continue
        group["Clock.Today"] = pd.to_datetime(group["Clock.Today"], errors="coerce")
        group = group.sort_values("Clock.Today")
        flowering = next(
            (
                value
                for value in (
                    _positive_number(item) for item in group["FloweringDAS"]
                )
                if value is not None
            ),
            None,
        )
        maturity_rows = group.loc[group["MaturityDAS"].map(_positive_number).notna()]
        matured = not maturity_rows.empty
        yield_kg_ha = _positive_number(
            pd.to_numeric(group["YieldKgHa"], errors="coerce").max()
        )
        biomass_kg_ha = _positive_number(
            pd.to_numeric(group["BiomassKgHa"], errors="coerce").max()
        )
        results[request.request_id] = SimulationResult(
            request_id=request.request_id,
            adapter_name=ADAPTER_NAME,
            adapter_version=adapter_version,
            status=RunStatus.MATURED if matured else RunStatus.NOT_MATURED,
            summary={
                "planting_date": request.management.planting_date.isoformat(),
                "flowering_proxy_dap": flowering,
                "flowering_date": (
                    (
                        request.management.planting_date
                        + timedelta(days=round(flowering))
                    ).isoformat()
                    if flowering is not None
                    else None
                ),
                "maturity_date": (
                    pd.Timestamp(maturity_rows.iloc[0]["Clock.Today"])
                    .date()
                    .isoformat()
                    if matured
                    else None
                ),
                "dry_yield_mg_ha": (
                    yield_kg_ha / 1000.0
                    if matured and yield_kg_ha is not None
                    else None
                ),
                "biomass_mg_ha": (
                    biomass_kg_ha / 1000.0
                    if biomass_kg_ha is not None
                    else None
                ),
                "juvenile_tt": float(
                    request.model_parameters.get("juvenile_tt", 211.0)
                ),
                "grain_number_scale": float(
                    request.model_parameters.get("grain_number_scale", 1.0)
                ),
            },
        )
    return results


@lru_cache(maxsize=4)
def _reported_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.search(r"APSIM\s+([0-9.]+)", completed.stdout)
    if not match:
        raise APSIMValidationError("cannot parse APSIM version")
    return match.group(1)


class APSIMAdapter:
    """Translate SnowWindow requests to APSIM Next Generation."""

    name = ADAPTER_NAME
    version = MODEL_VERSION

    def __init__(
        self,
        *,
        executable: Path | None = None,
        template_path: Path | None = None,
    ) -> None:
        root = _repo_root()
        self.executable = (executable or root / "bin/apsim").resolve()
        self.template_path = (
            template_path
            or root / ".tools/apsim/2026.9.8116.0/Examples/Maize.apsimx"
        ).resolve()

    @property
    def source_fingerprints(self) -> dict[str, str]:
        return {
            "adapter_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "apsim_template_sha256": hashlib.sha256(
                self.template_path.read_bytes()
            ).hexdigest(),
            "apsim_executable_sha256": hashlib.sha256(
                self.executable.read_bytes()
            ).hexdigest(),
        }

    def validate(self, request: SimulationRequest) -> None:
        if not self.executable.is_file() or not self.template_path.is_file():
            raise APSIMValidationError("APSIM executable or maize template is missing")
        parameters = dict(request.model_parameters)
        requested_version = str(parameters.get("model_version", self.version))
        if requested_version != self.version:
            raise APSIMValidationError(
                f"model version must be APSIM {self.version}"
            )
        if request.environment.environment_id != request.management.environment_id:
            raise APSIMValidationError("management environment does not match request")
        records = sorted(request.environment.weather, key=lambda item: item.date)
        expected = [timestamp.date() for timestamp in pd.date_range(
            request.start_date, request.end_date
        )]
        if [record.date for record in records] != expected:
            raise APSIMValidationError(
                "every calendar day in the inclusive simulation interval "
                "must have exactly one weather row"
            )
        for record in records:
            try:
                values = {name: float(record.values[name]) for name in REQUIRED_WEATHER}
            except (KeyError, TypeError, ValueError) as exc:
                raise APSIMValidationError(
                    "weather row is missing numeric required values"
                ) from exc
            if (
                not all(math.isfinite(value) for value in values.values())
                or values["T2M_MIN"] > values["T2M_MAX"]
                or values["PRECTOTCORR"] < 0
                or values["ALLSKY_SFC_SW_DWN"] < 0
            ):
                raise APSIMValidationError("weather values are physically invalid")
        juvenile_tt = float(parameters.get("juvenile_tt", 211.0))
        grain_scale = float(parameters.get("grain_number_scale", 1.0))
        if not 50 <= juvenile_tt <= 500:
            raise APSIMValidationError("juvenile_tt must be in [50, 500]")
        if not 0.1 <= grain_scale <= 3:
            raise APSIMValidationError("grain_number_scale must be in [0.1, 3]")

    def run(self, request: SimulationRequest) -> SimulationResult:
        return self.run_many((request,))[request.request_id]

    def run_many(
        self, requests: Iterable[SimulationRequest]
    ) -> dict[str, SimulationResult]:
        ordered = tuple(requests)
        if not ordered:
            return {}
        for request in ordered:
            self.validate(request)
        environments = {request.environment.environment_id for request in ordered}
        if len(environments) != 1:
            raise APSIMValidationError(
                "one APSIM batch must share one environment"
            )
        actual_version = _reported_version(str(self.executable))
        if actual_version != self.version:
            raise APSIMValidationError(
                f"installed APSIM version is {actual_version}, expected {self.version}"
            )
        output_dir = ordered[0].output_dir
        if output_dir is None:
            raise APSIMValidationError("APSIM requests require output_dir")
        request_identities = []
        for request in ordered:
            item = request.to_json_dict()
            item.pop("output_dir", None)
            item["environment"].pop("weather", None)
            request_identities.append(item)
        merged_weather = render_met_batch(ordered)
        identity = {
            "requests": request_identities,
            "weather_sha256": hashlib.sha256(merged_weather.encode()).hexdigest(),
            "version": actual_version,
            **self.source_fingerprints,
        }
        batch_key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        run_dir = Path(output_dir) / "apsim" / batch_key
        run_dir.mkdir(parents=True, exist_ok=True)
        met_path = run_dir / "weather.met"
        model_path = run_dir / "batch.apsimx"
        met_path.write_text(merged_weather, encoding="utf-8")
        document, name_to_id = build_apsim_document(
            self.template_path,
            ordered,
            weather_filename=met_path.name,
        )
        model_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        requests_by_simulation = {
            simulation_name: next(
                request for request in ordered if request.request_id == request_id
            )
            for simulation_name, request_id in name_to_id.items()
        }
        report_path = run_dir / "batch.Report.csv"
        if report_path.is_file():
            cached = parse_report(
                pd.read_csv(report_path),
                requests_by_simulation,
                adapter_version=self.version,
            )
            return {
                request_id: SimulationResult(
                    request_id=result.request_id,
                    adapter_name=result.adapter_name,
                    adapter_version=result.adapter_version,
                    status=result.status,
                    summary=result.summary,
                    artifacts={
                        "apsimx": model_path,
                        "weather": met_path,
                        "report": report_path,
                        "stdout": run_dir / "stdout.log",
                        "stderr": run_dir / "stderr.log",
                    },
                    diagnostics={"cache_key": batch_key, "cache_hit": True},
                    failure_reason=result.failure_reason,
                )
                for request_id, result in cached.items()
            }
        completed = subprocess.run(
            [
                str(self.executable),
                str(model_path),
                "--single-threaded",
                "--csv",
            ],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        (run_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip()
            return {
                request.request_id: SimulationResult(
                    request_id=request.request_id,
                    adapter_name=self.name,
                    adapter_version=self.version,
                    status=RunStatus.EXECUTION_FAILED,
                    artifacts={
                        "apsimx": model_path,
                        "weather": met_path,
                        "stdout": run_dir / "stdout.log",
                        "stderr": run_dir / "stderr.log",
                    },
                    diagnostics={"cache_key": batch_key},
                    failure_reason=reason[-2000:],
                )
                for request in ordered
            }
        report = (
            pd.read_csv(report_path)
            if report_path.is_file()
            else pd.DataFrame(
                columns=[
                    "SimulationName",
                    "Clock.Today",
                    "Maize.Phenology.CurrentStageName",
                    "FloweringDAS",
                    "MaturityDAS",
                    "YieldKgHa",
                    "BiomassKgHa",
                ]
            )
        )
        results = parse_report(
            report,
            requests_by_simulation,
            adapter_version=self.version,
        )
        return {
            request_id: SimulationResult(
                request_id=result.request_id,
                adapter_name=result.adapter_name,
                adapter_version=result.adapter_version,
                status=result.status,
                summary=result.summary,
                artifacts={
                    "apsimx": model_path,
                    "weather": met_path,
                    "report": report_path,
                    "stdout": run_dir / "stdout.log",
                    "stderr": run_dir / "stderr.log",
                },
                diagnostics={"cache_key": batch_key},
                failure_reason=result.failure_reason,
            )
            for request_id, result in results.items()
        }
