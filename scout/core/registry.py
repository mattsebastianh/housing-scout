from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ProviderBundle:
    scrape: Callable
    enrichers: dict[str, Callable] = field(default_factory=dict)
    regulatory: dict[str, Callable] = field(default_factory=dict)
    geocode_country: str = ""
    portal_base: str = ""
    slug_for: Callable[[str], str] = lambda name: name


_REGISTRY: dict[tuple[str, str], ProviderBundle] = {}


def register(country: str, portal: str, bundle: ProviderBundle) -> None:
    _REGISTRY[(country, portal)] = bundle


def resolve(country: str, portal: str) -> ProviderBundle:
    try:
        return _REGISTRY[(country, portal)]
    except KeyError:
        raise KeyError(
            f"No provider registered for country={country!r} portal={portal!r}. "
            f"Available: {sorted(_REGISTRY)}"
        )
