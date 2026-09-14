"""
extractor.py
------------
Turns raw invoice text (what an OCR / PDF text-extraction step would hand you)
into a structured JSON record using Claude.

Two modes, controlled by the MOCK_MODE env var:

  MOCK_MODE=true   (default) -> reads from data/mock_extractions.json.
                     Lets anyone clone this repo and run the full pipeline
                     immediately, with no API key and no cost.

  MOCK_MODE=false  -> calls the real Claude API. This is the actual
                     extraction path the project is built to demonstrate.

Both paths return the exact same schema, so validator.py and
report_generator.py never need to know which one ran.
"""

import os
import re
import json
from pathlib import Path

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

DATA_DIR = Path(__file__).parent / "data"

EXTRACTION_PROMPT = """You are extracting structured data from an invoice's raw text \
(the output of an OCR or PDF text-extraction step — formatting may be messy).

Return ONLY valid JSON. No preamble, no markdown code fences, no commentary.

Schema:
{{
  "invoice_number": string,
  "invoice_date": string (ISO 8601 "YYYY-MM-DD" if you can determine it, else as written),
  "vendor": string,
  "bill_to_entity": string,
  "po_reference": string or null,
  "currency": string (ISO 4217 code, e.g. EUR, USD),
  "line_items": [{{"description": string, "amount": number}}],
  "subtotal": number or null,
  "total_amount": number,
  "self_reported_confidence": "high" | "medium" | "low"
}}

Rules:
- If a field is missing, illegible, or genuinely ambiguous on the invoice, use null. \
Never invent a value.
- self_reported_confidence must be "low" whenever anything on the invoice is \
inconsistent, ambiguous, or missing (e.g. no PO reference, line items that don't \
sum to the stated total, unclear currency). This flag exists so a human reviewer \
knows where to look first — do not default it to "high" out of politeness.
- Extract amounts as numbers, not strings. Strip currency symbols and thousands separators.

Invoice text:
---
{invoice_text}
---
"""


def extract_with_claude(invoice_text: str) -> dict:
    """Real extraction path. Requires ANTHROPIC_API_KEY in the environment."""
    from anthropic import Anthropic

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "user", "content": EXTRACTION_PROMPT.format(invoice_text=invoice_text)}
        ],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude did not return valid JSON for this invoice. "
            f"Raw response was:\n{raw}"
        ) from e


def extract_mock(invoice_id: str) -> dict:
    """Demo path: pre-generated extractions, identical schema to the live path."""
    with open(DATA_DIR / "mock_extractions.json") as f:
        mocks = json.load(f)
    if invoice_id not in mocks:
        raise KeyError(
            f"No mock extraction found for '{invoice_id}'. Add one to "
            f"data/mock_extractions.json, or set MOCK_MODE=false and provide "
            f"a real ANTHROPIC_API_KEY to extract it live."
        )
    return mocks[invoice_id]


def extract_invoice(invoice_id: str, invoice_text: str) -> dict:
    if MOCK_MODE:
        return extract_mock(invoice_id)
    return extract_with_claude(invoice_text)
