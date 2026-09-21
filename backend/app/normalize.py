from __future__ import annotations

from typing import Any

from .store import load_demo


def normalize_fact(vendor_id: str, fact: dict[str, Any], terms: dict[str, Any]) -> dict[str, Any]:
    data = load_demo()
    rfx = data["rfx"]
    item = rfx["items"][fact["line_no"] - 1]
    basis = fact["raw_basis"]
    raw = fact.get("raw_price")
    steps: list[str] = []

    if basis == "piece":
        unit = float(raw)
        steps.append(f"{raw} {fact['raw_currency']} / piece")
    elif basis == "100_piece":
        unit = float(raw) / 100
        steps.append(f"{raw} {fact['raw_currency']} / 100 pcs -> divide by 100")
    elif basis == "carton":
        unit = float(raw) / int(fact["pack_size"])
        steps.append(f"{raw} INR / carton -> divide by {fact['pack_size']} pcs")
    elif basis == "bundle":
        unit = float(raw) / int(fact["pack_size"])
        steps.append(f"{raw} INR / bundle -> divide by {fact['pack_size']} pcs")
    elif basis == "kg":
        unit = float(raw) * float(item["unit_weight_kg"])
        steps.append(f"{raw} INR/kg × {item['unit_weight_kg']} kg/pc")
    elif basis == "same_as_last_year":
        unit = float(item["baseline_unit_price_inr"])
        steps.append(f"Resolve 'same as last year' to RFx baseline {unit} INR/pc")
    else:
        raise ValueError(f"Unsupported quote basis: {basis}")

    if fact.get("raw_currency") == "USD":
        unit *= float(rfx["commercial_rules"]["fx_rate_usd_inr"])
        steps.append(f"Convert USD -> INR at {rfx['commercial_rules']['fx_rate_usd_inr']}")

    landed = unit
    if vendor_id == "boxworks" and terms.get("freight_per_piece_inr") is not None:
        landed += float(terms["freight_per_piece_inr"])
        steps.append(f"Add freight {terms['freight_per_piece_inr']} INR/pc")
    elif vendor_id == "greencarton" and terms.get("freight_percent") is not None:
        landed *= 1 + float(terms["freight_percent"])
        steps.append(f"Add freight {terms['freight_percent']*100:.0f}% of material value")
    else:
        steps.append("Freight included / no freight adjustment")

    return {
        "line_no": fact["line_no"],
        "sku": fact["sku"],
        "normalized_unit_price_inr": round(unit, 2),
        "landed_unit_cost_inr": round(landed, 2),
        "steps": steps,
        "evidence": fact.get("evidence"),
    }
