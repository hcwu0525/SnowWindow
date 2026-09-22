"""Interfaces for crop-model adapters."""

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from snowwindow.domain import SimulationRequest, SimulationResult


@runtime_checkable
class ModelAdapter(Protocol):
    """Boundary implemented by each supported crop model."""

    @property
    def name(self) -> str:
        """Stable adapter name used in configuration."""

    @property
    def version(self) -> str:
        """Version of the underlying model implementation."""

    def validate(self, request: SimulationRequest) -> None:
        """Raise a useful error when a request cannot be run."""

    def run(self, request: SimulationRequest) -> SimulationResult:
        """Run one simulation request."""


class AdapterRegistry:
    """Name-based registry for model adapters."""

    def __init__(self, adapters: Iterable[ModelAdapter] = ()) -> None:
        self._adapters: dict[str, ModelAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ModelAdapter) -> None:
        name = adapter.name.strip()
        if not name:
            raise ValueError("adapter name must be nonempty")
        if name in self._adapters:
            raise ValueError(f"adapter {name!r} is already registered")
        self._adapters[name] = adapter

    def get(self, name: str) -> ModelAdapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            available = ", ".join(self.names()) or "none"
            raise KeyError(
                f"unknown adapter {name!r}; available adapters: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
