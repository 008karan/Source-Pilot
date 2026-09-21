from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "demo-data" / "generated"


@lru_cache(maxsize=1)
def load_demo() -> dict[str, Any]:
    return json.loads((DATA_DIR / "demo_state.json").read_text(encoding="utf-8"))


def public_event() -> dict[str, Any]:
    data = load_demo()
    rfx = data["rfx"]
    vendors = data["vendors"]
    return {
        "event_id": rfx["event_id"],
        "title": rfx["title"],
        "category": rfx["category"],
        "buyer": rfx["buyer"],
        "expected_annual_spend_inr": rfx["expected_annual_spend_inr"],
        "stage": "ready_for_analysis",
        "line_count": len(rfx["items"]),
        "vendor_count": len(vendors),
        "exception_count": len(data["exceptions"]),
        "vendors": [
            {
                "id": vid,
                "name": v["name"],
                "format": v["format"],
                "quality": v["quality"],
                "lead_days": v["lead"],
                "coverage": sum(1 for x in v["lines"] if x["quote_status"] == "quoted"),
            }
            for vid, v in vendors.items()
        ],
    }


def evidence_detail(evidence_id: str) -> dict[str, Any] | None:
    data = load_demo()
    ref = data["evidence"].get(evidence_id)
    if not ref:
        return None
    detail = dict(ref)
    detail["id"] = evidence_id
    # attach transformation from the comparison cell
    for row in data["comparison"]:
        for vendor_id, quote in row["vendors"].items():
            if quote.get("evidence_id") == evidence_id:
                detail.update(
                    {
                        "line_no": row["line_no"],
                        "sku": row["sku"],
                        "description": row["description"],
                        "vendor_id": vendor_id,
                        "vendor_name": data["vendors"][vendor_id]["name"],
                        "confidence": quote.get("confidence"),
                        "normalized_unit_price": quote.get("unit_price"),
                        "landed_unit_cost": quote.get("landed_unit_cost"),
                        "transformation_steps": quote.get("transformation_steps", []),
                    }
                )
                return detail
    return detail
