from scout.core.score.compose import composite

# Mirrors config.yaml → scoring.weights (the runtime source of truth).
WEIGHTS: dict[str, float] = {
    "price": 0.18,
    "location": 0.20,
    "commute": 0.15,
    "legal": 0.15,
    "regulatory": 0.07,
    "environmental": 0.10,
    "neighbourhood": 0.10,
    "infrastructure": 0.05,
}


def test_composite_all_present():
    """All dimensions present with equal scores return that score exactly."""
    scores = {k: 5.0 for k in WEIGHTS}
    assert composite(scores, WEIGHTS) == 5.0


def test_composite_renormalises_when_missing():
    """A missing dimension is excluded from the weighted sum and the remaining weights are renormalised."""
    scores = {k: 10.0 for k in WEIGHTS if k != "infrastructure"}
    scores["infrastructure"] = None
    assert composite(scores, WEIGHTS) == 10.0


def test_composite_zero_when_all_missing():
    """All-None dimension scores return 0.0."""
    assert composite({k: None for k in WEIGHTS}, WEIGHTS) == 0.0


def test_composite_proportional_renorm():
    """Two present scores are weighted proportionally after renormalisation over only those two dimensions."""
    scores = {k: None for k in WEIGHTS}
    scores["price"] = 10.0
    scores["location"] = 0.0
    expected = (10.0 * WEIGHTS["price"]) / (WEIGHTS["price"] + WEIGHTS["location"])
    assert abs(composite(scores, WEIGHTS) - expected) < 0.01


def test_composite_uses_supplied_weights():
    """Different weight dicts produce different composites — config changes take effect."""
    scores = {"location": 10.0, "commute": 0.0}
    location_heavy = composite(scores, {"location": 0.9, "commute": 0.1})
    commute_heavy = composite(scores, {"location": 0.1, "commute": 0.9})
    assert location_heavy == 9.0
    assert commute_heavy == 1.0
