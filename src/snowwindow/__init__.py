"""SnowWindow experiment foundations."""

from snowwindow.adapters import AdapterRegistry, ModelAdapter
from snowwindow.config import (
    ConfigError,
    ExperimentConfig,
    ModelConfig,
    SelectionConfig,
    SimulationConfig,
    load_config,
)
from snowwindow.data import PreparationResult, audit_g2f, prepare_g2f
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    Observation,
    RunStatus,
    SimulationRequest,
    SimulationResult,
    SoilLayer,
    WeatherRecord,
)

__all__ = [
    "AdapterRegistry",
    "ConfigError",
    "Environment",
    "ExperimentConfig",
    "ManagementUnit",
    "ModelAdapter",
    "ModelConfig",
    "Observation",
    "PreparationResult",
    "RunStatus",
    "SelectionConfig",
    "SimulationConfig",
    "SimulationRequest",
    "SimulationResult",
    "SoilLayer",
    "WeatherRecord",
    "audit_g2f",
    "load_config",
    "prepare_g2f",
]

__version__ = "0.1.0"
