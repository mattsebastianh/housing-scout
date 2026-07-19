import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

from scout.core.models import EnrichedListing

Enricher = Callable[[EnrichedListing, httpx.AsyncClient], Awaitable["EnrichmentResult"]]


@dataclass
class EnrichmentResult:
    success: bool
    payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None


async def _safe(name: str, fn: Enricher, item: EnrichedListing, client: httpx.AsyncClient) -> tuple[str, EnrichmentResult]:
    try:
        result = await fn(item, client)
        return name, result
    except Exception as exc:
        return name, EnrichmentResult(success=False, error=f"{type(exc).__name__}: {exc}")


async def run_enrichers(
    item: EnrichedListing,
    client: httpx.AsyncClient,
    enrichers: dict[str, Enricher],
) -> dict[str, EnrichmentResult]:
    tasks = [_safe(name, fn, item, client) for name, fn in enrichers.items()]
    pairs = await asyncio.gather(*tasks)
    return dict(pairs)
