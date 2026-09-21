# Source Pilot

A sourcing decision room: describe what you need to buy, collect supplier responses in
whatever format they arrive in, normalize them into one comparable basis, and ask
questions about the result.

Every number on screen is computed — the model reads documents and interprets your
question, but an optimizer produces the figures, and each one traces back to a line in
a source document.

## What it does

| Step | Screen | What happens |
| --- | --- | --- |
| 1 | RFx Builder | A chat that turns a requirement into a structured brief. Attach a sheet or PDF and the line items are extracted and mapped to the checklist. |
| 2 | Responses | Supplier replies as Excel, PDF, Word, email or a photo of a rate card. Extraction runs only when you ask for it. |
| 3 | Review & Compare | Landed costs on one basis, with an exception inbox for everything that needs a human decision before an award. |
| 4 | Analysis Room | Ask for per-SKU winners, award splits, or a comparison between strategies. Answers come with the chart that supports them. |

## Run it locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add your key; .env is gitignored
set -a; . ./.env; set +a
.venv/bin/python run_demo.py --port 8000
```

Then open http://127.0.0.1:8000.

## Deploy on Railway

1. Create a project from this repository. Nixpacks detects Python from
   `requirements.txt` and `.python-version`; `railway.json` supplies the start command.
2. Set the variables under **Variables**:

   | Variable | Value |
   | --- | --- |
   | `GOOGLE_API_KEY` | your Gemini API key |
   | `GEMINI_MODEL` | `gemini-3.8-flash` (optional) |
   | `AERCHAIN_DATA_DIR` | `/data` — see below |

3. Attach a **Volume** mounted at `/data`. Without one the container filesystem is
   ephemeral, so every redeploy starts from an empty event. With it, your snapshots,
   uploads and audit history persist.

`PORT` is provided by Railway; `run_demo.py` binds `0.0.0.0` whenever `PORT` is set and
stays on `127.0.0.1` otherwise, so local runs are never exposed by accident.

## The packaging example

`demo-data/generated/` holds the worked example — a 30-line corrugated packaging event
and five supplier responses, one in each format:

| Supplier | Format | What it exercises |
| --- | --- | --- |
| PackRight Industries | `.xlsx` | Clean workbook, per-piece pricing |
| CorrPro International | `.pdf` | Quotes in USD, freight stated separately |
| BoxWorks India | `.docx` | Carton pack sizes instead of pieces; three lines unquoted |
| AlphaPack Solutions | `.jpg` | A photograph of a rate card — needs the vision model |
| GreenCarton Co. | `.eml` | Prices per kilogram, buried in an email body |

To walk through it: **RFx Builder → use the packaging example → approve and release →
Responses → Load demo messages → Extract & normalize**.

Without `GOOGLE_API_KEY` the first, second, third and fifth extract deterministically;
the photograph needs the key.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

145 tests, covering document intake, currency and pack-size normalization, freight
apportionment, the award optimizer, the knowledge graph, and the type scale.
