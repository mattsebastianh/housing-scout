from typing import Optional


def composite(scores: dict[str, Optional[float]], weights: dict[str, float]) -> float:
    """Weighted composite of the available dimension scores.

    ``weights`` comes from ``config.yaml → scoring.weights`` (the single source
    of truth — there is deliberately no default here). Dimensions scored None
    are excluded and the remaining weights renormalised.
    """
    available = {k: v for k, v in scores.items() if v is not None}
    if not available:
        return 0.0
    weighted_sum = sum(v * weights[k] for k, v in available.items())
    weight_total = sum(weights[k] for k in available)
    return round(weighted_sum / weight_total, 2)
