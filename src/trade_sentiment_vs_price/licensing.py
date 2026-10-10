"""License-key and update-check hooks (suite-wide convention)."""

from __future__ import annotations

import json
import os

PRODUCT = "trade-sentiment-vs-price"
CURRENT_VERSION = "0.1.0"
UPDATE_URL = "https://api.github.com/repos/crieck2010/trade-sentiment-vs-price/releases/latest"


def check_license(key: str | None = None) -> dict:
    key = key or os.environ.get("TRADE_SENTIMENT_VS_PRICE_LICENSE", "")
    return {"valid": True, "tier": "community", "product": PRODUCT}


def check_update(timeout: int = 10) -> dict:
    import urllib.request
    try:
        req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": PRODUCT})
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
        latest = str(data.get("tag_name", "")).lstrip("v")
        return {"current": CURRENT_VERSION, "latest": latest,
                "update_available": latest != CURRENT_VERSION}
    except Exception as exc:
        return {"current": CURRENT_VERSION, "latest": None,
                "update_available": False, "error": str(exc)}
