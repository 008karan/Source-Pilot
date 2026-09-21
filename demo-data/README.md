# Demo dataset - FY27 Corrugated Packaging

This folder contains a deliberately messy five-vendor sourcing event designed to exercise the take-home assignment's ugly edges.

Run `python scripts_generate_demo.py` to regenerate everything under `demo-data/generated/`.

## Supplier response matrix

| Supplier | Format | Coverage | Designed edge cases |
|---|---|---:|---|
| PackRight Industries | XLSX | 30/30 | Ignores template; per-piece vs per-100-piece basis across rows; terms/questionnaire on separate sheets |
| CorrPro International | PDF | 30/30 | USD / 100 pcs; DDP; 3% conditional annual rebate hidden in a footnote |
| BoxWorks India Pvt Ltd | DOCX | 27/30 | Missing three lines; mixed carton/each pricing; explicit pack sizes; freight extra; quality certificate expiry |
| AlphaPack Solutions | angled JPG | 30/30 | Phone-photo style rate card; bundle units; obscured high-impact price; mandatory FSC failure |
| GreenCarton Co. | EML | 30/30 | Rates in INR/kg; four lines say `same as last year`; freight is 2% of material value |

## Ground truth

- `rfx.json` is the canonical RFx.
- `demo_state.json` is the full demo truth: supplier facts, normalized comparison, evidence pointers and exceptions.
- `normalized_truth.csv` is a flat inspection file for verifying 150 supplier-line states.
- `manifest.json` explains every generated source file and the intended edge cases.

The buyer baseline and unit weights are intentionally part of the RFx so the application can trace conversions such as INR/kg -> INR/piece without inventing a conversion factor.
