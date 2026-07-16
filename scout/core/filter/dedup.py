import re
import unicodedata

from scout.core.models import Listing

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_MULTI_SPACE = re.compile(r"\s+")
_ORDINAL_CHARS = str.maketrans({"º": " ", "ª": " ", "°": " "})


def normalise_address(address: str, municipality: str) -> str:
    def _strip(s: str) -> str:
        s = s.translate(_ORDINAL_CHARS)
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode("ascii")
        s = s.lower()
        s = _NON_ALNUM.sub(" ", s)
        s = _MULTI_SPACE.sub(" ", s).strip()
        return s

    return f"{_strip(address)}|{_strip(municipality)}"


def dedup_key(r: Listing) -> str:
    if r.cadastral_ref:
        return f"cad:{r.cadastral_ref.strip().upper()}"
    if r.address and r.municipality:
        return f"addr:{normalise_address(r.address, r.municipality)}"
    if r.price_eur and r.size_m2 and r.municipality:
        # Fixed 5 000 € price bands and 5 m² bands. Stricter than 5 % across the
        # whole 100–200 k € band; favours false negatives over collapsing distinct
        # properties.
        price_bucket = r.price_eur // 5000
        m2_bucket = r.size_m2 // 5
        muni = r.municipality.strip().lower()
        return f"approx:{muni}:{price_bucket}:{m2_bucket}"
    return f"id:{r.portal}:{r.external_id}"
