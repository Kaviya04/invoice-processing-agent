# Invoice Processing Agent

AI-assisted invoice extraction with a deterministic validation layer sitting
between Claude's output and anything that gets paid. Built to mirror the
kind of accounts-payable workflow a finance team actually runs: PDFs come
in, structured data needs to come out, and someone is accountable for
every number that gets approved.

The premise this project is built around: **in finance, 99% right is
wrong.** An LLM extraction is a first draft, not a decision. This project
is really about the validation layer, not the extraction — Claude reads
the invoice, but a separate, auditable set of checks decides what happens
to it.

---

## What it does

1. **Extracts** structured data from raw invoice text (what an OCR / PDF
   text-extraction step would hand you) using Claude, with a
   self-reported confidence flag baked into the extraction schema.
2. **Validates** every extraction independently against a PO master, a
   vendor master, and the invoice's own internal math — Claude's
   confidence is treated as one signal among several, not a verdict.
3. **Triages** each invoice into one of three tiers and exports an Excel
   report an AP reviewer could actually work from.

| Tier | Meaning |
|---|---|
| `AUTO_APPROVED` | Extraction is internally consistent and matches the PO, vendor, and currency on file. |
| `NEEDS_REVIEW` | One or more checks failed — missing PO, amount mismatch, unknown vendor, currency mismatch, math that doesn't add up, or low model confidence. |
| `REJECTED` | Same invoice number already processed in this batch — hard-blocked, not routed to review. |

---

## Sample output

```
==============================================================
  INVOICE PROCESSING AGENT  —  MOCK MODE
==============================================================
  ✓  Extracted INV-1001
  ✓  Extracted INV-1002
  ...
  ✓  Extracted INV-1012

--------------------------------------------------------------
  Auto-approved   : 5
  Needs review    : 6
  Rejected        : 1
--------------------------------------------------------------
  Report saved to: output/invoice_report_2026-09-14.xlsx
==============================================================
```

Per-invoice flags from the included test batch:

| Invoice | Decision | Flags |
|---|---|---|
| INV-1001 | Auto-Approved | — |
| INV-1002 | Needs Review | `LINE_ITEM_MISMATCH`, `AMOUNT_EXCEEDS_PO` — line items sum to $6,710 but the invoice states $6,900 |
| INV-1003 | Needs Review | `MISSING_PO`, `LOW_EXTRACTION_CONFIDENCE` |
| INV-1004 | Needs Review | `AMOUNT_EXCEEDS_PO` — invoice is $2,400 vs a $1,800 PO |
| INV-1005 | **Rejected** | `DUPLICATE_INVOICE_NUMBER` — resubmission of INV-1001, caught by the invoice's own stated number, not the filename |
| INV-1006 | Needs Review | `CURRENCY_MISMATCH` — billed in USD against a EUR PO |
| INV-1007 | Needs Review | `PO_NOT_FOUND`, `UNKNOWN_VENDOR` |
| INV-1008–1010 | Auto-Approved | — |
| INV-1011 | Auto-Approved | $0.05 rounding difference vs PO — within tolerance |
| INV-1012 | Needs Review | `AMOUNT_EXCEEDS_PO` — invoice is $1,100 vs a $500 PO |

Every one of these is a deliberately planted test case (see
[Why these test cases](#why-these-test-cases-exist)) — this isn't a lucky
run, it's what the validation layer is designed to catch.

---

## Project structure

```
invoice-processing-agent/
├── data/
│   ├── invoices/               # 12 synthetic invoices as raw text
│   ├── po_master.csv           # ground-truth PO data to validate against
│   ├── vendor_master.csv       # approved vendor list
│   └── mock_extractions.json   # pre-generated Claude-equivalent output (demo mode)
├── output/
│   └── invoice_report_YYYY-MM-DD.xlsx
├── extractor.py                 # Claude extraction (+ mock fallback)
├── validator.py                 # the actual point of the project
├── report_generator.py          # Excel export, tiered by decision
├── main.py                      # orchestrates the pipeline
└── requirements.txt
```

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Runs immediately with **no API key** — `MOCK_MODE=true` by default reads
from `data/mock_extractions.json`, which mirrors exactly what a live
Claude call returns. This is so anyone reviewing this repo can run it
end-to-end without me paying an API bill on their behalf.

To run live extraction against the real Claude API:

```bash
# in .env:
ANTHROPIC_API_KEY=sk-ant-...
MOCK_MODE=false

python main.py
```

---

## Why these test cases exist

Real invoice batches aren't clean, so the 12 sample invoices aren't
either. Each one is a deliberate probe of a specific failure mode an AP
process has to handle:

- **Math that doesn't reconcile** (INV-1002): line items sum to one
  number, the stated total is another. Real invoices have this — partial
  payments, add-on line items, rounding. Caught independently of what
  Claude "believes" the total is.
- **No PO at all** (INV-1003): can't validate what isn't there. Routed to
  review rather than silently approved.
- **PO exists but the amount is wrong** (INV-1004, INV-1012): the
  extraction itself is fine — this is a business rule check, not an
  extraction error, and the two need to be told apart.
- **Duplicate submission** (INV-1005): same invoice, resent by the vendor
  under a new filename. Caught by the invoice's own stated number, which
  is why the check runs on extracted data, not on filenames.
- **Currency mismatch against the PO** (INV-1006): easy to miss if you
  only check amounts and ignore currency codes — directly relevant to
  any team running multiple entities in multiple currencies.
- **Unknown vendor and unknown PO together** (INV-1007): a new vendor
  invoicing without an approved PO — exactly the pattern AP fraud
  training flags as worth a second look.
- **Genuinely clean, including one with a sub-dollar rounding gap**
  (INV-1001, 1008–1011): the system has to *not* flag things that don't
  need a human, or the review queue becomes noise nobody trusts.

---

## Skills demonstrated

- **Prompt design for structured extraction**: schema-constrained JSON
  output, explicit null-handling rules, and a self-reported confidence
  field that's instructed not to default to "high."
- **Independent validation, not trust**: every extracted field is
  cross-checked against ground-truth data (PO master, vendor master,
  internal math) rather than accepted as-is — the design assumes the
  model will sometimes be right about the wrong thing.
- **Finance domain logic**: PO matching, tolerance thresholds vs. hard
  mismatches, duplicate-payment prevention, vendor approval status,
  multi-currency handling.
- **Python**: dataclasses, CSV/JSON I/O, openpyxl report generation,
  environment-based configuration (mock vs. live modes).

---

## Extending this

- Swap the `.txt` inputs for real PDFs using Claude's document/vision
  input instead of a separate OCR step.
- Add a GL-code suggestion step once an invoice is auto-approved.
- Log every decision (not just flags) to a `decisions.csv` for an audit
  trail — currently the Excel report is the only output artifact.
- Add a Slack/email notification for anything landing in `NEEDS_REVIEW`
  above a value threshold.
- Swap the CSV masters for a real accounting system export (Exact
  Online, QuickBooks) or a live PO API.
