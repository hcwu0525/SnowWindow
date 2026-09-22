"""Public G2F normalization and audit interface."""

from snowwindow.data.audit import audit_weather_coverage
from snowwindow.data.normalization import (
    aggregate_representative_maize,
    classify_severe_issue,
    derive_soil_profiles,
    normalize_irrigation,
    resolve_coordinates,
)
from snowwindow.data.preparation import PreparationResult, audit_g2f, prepare_g2f
from snowwindow.data.sources import (
    DataPreparationError,
    parse_g2f_date,
    validate_training_natural_keys,
)

__all__ = [
    "DataPreparationError",
    "PreparationResult",
    "aggregate_representative_maize",
    "audit_g2f",
    "audit_weather_coverage",
    "classify_severe_issue",
    "derive_soil_profiles",
    "normalize_irrigation",
    "parse_g2f_date",
    "prepare_g2f",
    "resolve_coordinates",
    "validate_training_natural_keys",
]
