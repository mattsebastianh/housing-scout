from scout.providers.es.regulatory.zonas_tensionadas import is_tensionada


def test_declared_catalan_municipality_is_tensionada():
    """Known Catalan ZMRT municipalities return True."""
    assert is_tensionada("Terrassa")
    assert is_tensionada("Sant Cugat del Vallès")
    assert is_tensionada("Sabadell")
    assert is_tensionada("Mataró")


def test_leading_article_stripped():
    """Leading articles (el/la/l') are normalised away before lookup."""
    assert is_tensionada("El Prat de Llobregat")
    assert is_tensionada("el prat de llobregat")
    assert is_tensionada("L'Hospitalet de Llobregat")


def test_case_insensitive():
    """Lookup is case-insensitive."""
    assert is_tensionada("terrassa")
    assert is_tensionada("SABADELL")


def test_valencia_municipalities_not_tensionada():
    """Valencia-area municipalities return False (no ZMRT declared in Comunitat Valenciana)."""
    assert not is_tensionada("Valencia")
    assert not is_tensionada("Torrent")
    assert not is_tensionada("Paterna")


def test_rural_municipality_not_tensionada():
    """Rural municipalities outside the ZMRT set return False."""
    assert not is_tensionada("Montserrat")
    assert not is_tensionada("Vilafamés")


def test_none_returns_false():
    """None and empty string return False without raising."""
    assert not is_tensionada(None)
    assert not is_tensionada("")
