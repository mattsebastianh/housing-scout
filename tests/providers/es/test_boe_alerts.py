from scout.providers.es.regulatory.boe_alerts import filter_relevant


def test_filter_keeps_residential_property_keywords():
    """Keeps housing-related bulletin items and drops unrelated entries."""
    items = [
        {"title": "Real Decreto sobre vivienda en alquiler", "summary": "tope de precios"},
        {"title": "Subvenciones agrícolas", "summary": ""},
        {"title": "Modificación Ley de la Vivienda", "summary": "zonas tensionadas"},
    ]
    kept = filter_relevant(items)
    titles = [k["title"] for k in kept]
    assert "Real Decreto sobre vivienda en alquiler" in titles
    assert "Modificación Ley de la Vivienda" in titles
    assert "Subvenciones agrícolas" not in titles
