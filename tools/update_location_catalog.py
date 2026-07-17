"""Generate assets/locations.json from the versioned Star Citizen Wiki position feed.

Run manually when preparing an SCHT release. The desktop application uses only
the generated offline snapshot and never requires network access.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.star-citizen.wiki/api/locations/positions"
ROOT = Path(__file__).resolve().parents[1]


def useful_name(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value and not re.search(r"(?:UNINITIALIZED|PLACEHOLDER|^WIP\b)", value, re.I))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="Optional LIVE game-data version pin")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "locations.json")
    args = parser.parse_args()
    url = API_URL
    if args.version:
        url += "?" + urllib.parse.urlencode({"version": args.version})
    request = urllib.request.Request(url, headers={"User-Agent": "SCHT-location-catalog/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    source = payload.get("data") or []
    by_id = {str(item.get("uuid") or ""): item for item in source}
    overrides_path = ROOT / "assets" / "location_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    alias_targets = overrides.get("aliases") or {}
    aliases_by_id = {}
    for alias, target in alias_targets.items():
        aliases_by_id.setdefault(str(target), []).append(str(alias))
    locations = []
    for item in source:
        uuid = str(item.get("uuid") or "").strip()
        name = str(item.get("name") or "").strip()
        if not uuid or not useful_name(name):
            continue
        parent = by_id.get(str(item.get("parent_uuid") or "")) or {}
        locations.append({
            "id": uuid, "name": name, "system": str(item.get("system") or "").title(),
            "parent": str(parent.get("name") or ""), "type": str(item.get("type") or ""),
            "qt_valid": bool(item.get("qt_valid")),
            "position_m": [item.get("x"), item.get("y"), item.get("z")]
            if all(item.get(axis) is not None for axis in ("x", "y", "z")) else None,
            "aliases": sorted(aliases_by_id.get(uuid, []), key=str.casefold),
        })
    locations.sort(key=lambda item: (item["system"].casefold(), item["name"].casefold(), item["id"]))
    output = {
        "schema_version": 1, "source": API_URL, "game_version": args.version or "default",
        "generated_at": datetime.now(timezone.utc).isoformat(), "coordinate_frame": "system-space",
        "coordinate_unit": "metre", "locations": locations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(locations)} locations to {args.output}")


if __name__ == "__main__":
    main()
