"""Public G2F normalization and audit interface."""

from snowwindow.data.audit import audit_weather_coverage, evaluate_eligibility
from snowwindow.data.normalization import (
    add_density_to_management_units,
    aggregate_representative_maize,
    classify_severe_issue,
    classify_usda_texture,
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
    "add_density_to_management_units",
    "aggregate_representative_maize",
    "audit_g2f",
    "audit_weather_coverage",
    "classify_severe_issue",
    "classify_usda_texture",
    "derive_soil_profiles",
    "evaluate_eligibility",
    "normalize_irrigation",
    "parse_g2f_date",
    "prepare_g2f",
    "resolve_coordinates",
    "validate_training_natural_keys",
]
