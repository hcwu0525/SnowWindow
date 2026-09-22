"""AquaCrop 3.1.0 adapter boundary."""

from snowwindow.adapters import AdapterRegistry
from snowwindow.models.aquacrop.adapter import (
    AquaCropAdapter,
    map_crop_state,
    map_exception_status,
    simulation_end_for_planting,
)
from snowwindow.models.aquacrop.physics import reference_et


def default_adapter_registry() -> AdapterRegistry:
    """Return the built-in registry with the pinned AquaCrop adapter."""

    return AdapterRegistry((AquaCropAdapter(),))


__all__ = [
    "AquaCropAdapter",
    "default_adapter_registry",
    "map_crop_state",
    "map_exception_status",
    "reference_et",
    "simulation_end_for_planting",
]
