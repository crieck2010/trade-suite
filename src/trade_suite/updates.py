"""Update-check hook: compare against the latest GitHub release.

Stdlib only (``urllib``).  Network failures degrade gracefully to
``{"error": ...}`` so a missing connection never breaks the CLI.
"""

from __future__ import annotations

import json
import urllib.request

RELEASES_URL = "https://api.github.com/repos/crieck2010/trade-suite/releases/latest"
TIMEOUT_SECONDS = 8


def _parse_version(text: str) -> tuple[int, ...]:
    text = (text or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in text.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def check_for_updates(current_version: str, url: str = RELEASES_URL) -> dict:
    """Return ``{"latest": ..., "url": ..., "update_available": bool}``.

    On any failure returns ``{"error": <message>}`` instead of raising.
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "trade-suite",
                          "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network/DNS/JSON failures all land here
        return {"error": f"{type(exc).__name__}: {exc}"}

    latest = str(payload.get("tag_name") or payload.get("name") or "").strip()
    page = str(payload.get("html_url") or "")
    if not latest:
        return {"error": "release payload had no version tag"}
    return {
        "latest": latest,
        "url": page,
        "update_available": is_newer(latest, current_version),
    }
