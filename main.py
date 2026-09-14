"""
main.py
-------
Runs the full pipeline over every invoice in data/invoices/:

    extract (Claude, or mock)  ->  validate (deterministic checks)  ->  report (Excel)

Usage:
    python main.py                 # uses MOCK_MODE from .env (default: true)
    MOCK_MODE=false python main.py # live Claude extraction (needs ANTHROPIC_API_KEY)
"""

import os
from pathlib import Path
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from extractor import extract_invoice, MOCK_MODE
from validator import validate_batch
from report_generator import generate_report

DATA_DIR = Path(__file__).parent / "data" / "invoices"
OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    invoice_files = sorted(DATA_DIR.glob("*.txt"))

    if not invoice_files:
        print(f"No invoices found in {DATA_DIR}")
        return

    print("=" * 62)
    print(f"  INVOICE PROCESSING AGENT  —  {'MOCK MODE' if MOCK_MODE else 'LIVE (Claude API)'}")
    print("=" * 62)

    extractions = {}
    for path in invoice_files:
        invoice_id = path.stem
        text = path.read_text()
        try:
            extractions[invoice_id] = extract_invoice(invoice_id, text)
            print(f"  ✓  Extracted {invoice_id}")
        except Exception as e:
            print(f"  ✗  Failed to extract {invoice_id}: {e}")

    results = validate_batch(extractions)

    output_path = OUTPUT_DIR / f"invoice_report_{date.today().isoformat()}.xlsx"
    tiers = generate_report(results, output_path)

    print()
    print("-" * 62)
    print(f"  Auto-approved   : {len(tiers['AUTO_APPROVED'])}")
    print(f"  Needs review    : {len(tiers['NEEDS_REVIEW'])}")
    print(f"  Rejected        : {len(tiers['REJECTED'])}")
    print("-" * 62)
    print(f"  Report saved to: {output_path}")
    print("=" * 62)


if __name__ == "__main__":
    main()
