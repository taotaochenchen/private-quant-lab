"""Small dependency registry for replaceable data providers."""

from typing import Generic, TypeVar

ProviderT = TypeVar("ProviderT")


class ProviderRegistry(Generic[ProviderT]):
    def __init__(self) -> None:
        self._providers: dict[str, ProviderT] = {}

    def register(self, name: str, provider: ProviderT) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("provider name must not be empty")
        if normalized in self._providers:
            raise ValueError(f"provider already registered: {normalized}")
        self._providers[normalized] = provider

    def get(self, name: str) -> ProviderT:
        normalized = name.strip().lower()
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown provider: {normalized}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
