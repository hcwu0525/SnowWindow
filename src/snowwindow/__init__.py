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
    "RunStatus",
    "SelectionConfig",
    "SimulationConfig",
    "SimulationRequest",
    "SimulationResult",
    "SoilLayer",
    "WeatherRecord",
    "load_config",
]

__version__ = "0.1.0"
