from datetime import datetime, UTC

import httpx
import pytest
import respx

from scout.providers.es.enrich.catastro import enrich_catastro
from scout.core.models import EnrichedListing, Listing

_DNPRC_URL = (
    "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/"
    "COVCCallejero.svc/json/Consulta_DNPRC"
)
_WFS_URL = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"


def _item(**ov):
    base = dict(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=150000, size_m2=120, bedrooms=3, bathrooms=2,
        municipality="Terrassa", province="Barcelona", address="Carrer X 1",
        lat=41.5, lon=2.0, description="", days_on_market=0,
        cadastral_ref="1234567VK1213N0001AB", raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    base.update(ov)
    return EnrichedListing(listing=Listing(**base))


def _dnprc(luso="Residencial", cn="UR", wrapper="consulta_dnprcResult"):
    return {
        wrapper: {
            "bico": {
                "bi": {
                    "idbi": {"cn": cn},
                    "debi": {"luso": luso, "sfc": "165", "ant": "1998"},
                }
            }
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_catastro_parses_live_dnprcresult_shape():
    """Parses the live consulta_dnprcResult wrapper into use_code, year_built, built_m2, and urbanistic_class."""
    # Live JSON service wraps the body in `consulta_dnprcResult` with a
    # human-readable `luso` and string numerics.
    respx.get(_DNPRC_URL).mock(return_value=httpx.Response(200, json=_dnprc()))
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(), client)
    assert result.success
    assert result.payload["use_code"] == "Residencial"
    assert result.payload["year_built"] == 1998
    assert result.payload["built_m2"] == 165
    assert result.payload["urbanistic_class"] == "urbano"


@pytest.mark.asyncio
@respx.mock
async def test_catastro_back_compat_consulta_dnp_shape():
    """Accepts the alternative consulta_dnp wrapper key for backwards compatibility."""
    respx.get(_DNPRC_URL).mock(
        return_value=httpx.Response(200, json=_dnprc(luso="V", wrapper="consulta_dnp"))
    )
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(), client)
    assert result.success
    assert result.payload["use_code"] == "V"
    assert result.payload["built_m2"] == 165


@pytest.mark.asyncio
@respx.mock
async def test_catastro_maps_rustica_class_to_no_urbanizable():
    """Maps the RU class code to 'no urbanizable'."""
    respx.get(_DNPRC_URL).mock(return_value=httpx.Response(200, json=_dnprc(cn="RU")))
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(), client)
    assert result.success
    assert result.payload["urbanistic_class"] == "no urbanizable"


@pytest.mark.asyncio
@respx.mock
async def test_catastro_resolves_ref_from_coords_when_missing():
    """Falls back to WFS coord lookup when cadastral_ref is absent, then calls DNPRC with the resolved ref."""
    # No cadastral_ref → WFS coords lookup → then DNPRC with the resolved ref.
    wfs_xml = (
        '<wfs:FeatureCollection xmlns:cp="x" xmlns:wfs="y">'
        "<cp:nationalCadastralReference>0245708VK4704C</cp:nationalCadastralReference>"
        "</wfs:FeatureCollection>"
    )
    wfs_route = respx.get(_WFS_URL).mock(return_value=httpx.Response(200, text=wfs_xml))
    dnprc_route = respx.get(_DNPRC_URL).mock(return_value=httpx.Response(200, json=_dnprc()))
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(cadastral_ref=None), client)
    assert wfs_route.called
    assert dnprc_route.called
    # the DNPRC request used the WFS-resolved reference
    assert dnprc_route.calls.last.request.url.params["RefCat"] == "0245708VK4704C"
    assert result.success
    assert result.payload["use_code"] == "Residencial"


@pytest.mark.asyncio
@respx.mock
async def test_catastro_coords_lookup_empty_fails_soft():
    """Soft-fails when the WFS response contains no cadastral reference for the given coords."""
    respx.get(_WFS_URL).mock(return_value=httpx.Response(200, text="<empty/>"))
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(cadastral_ref=None), client)
    assert result.success is False
    assert "coords lookup failed" in (result.error or "")


@pytest.mark.asyncio
async def test_catastro_no_ref_no_coords_skips():
    """Soft-fails immediately when both cadastral_ref and coordinates are absent."""
    async with httpx.AsyncClient() as client:
        result = await enrich_catastro(_item(cadastral_ref=None, lat=None, lon=None), client)
    assert result.success is False
