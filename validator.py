"""
validator.py
------------
This is the actual point of the project: Claude's extraction is never
trusted on its own. Every extracted invoice runs through independent,
deterministic checks against the PO master, the vendor master, and its
own internal math before a decision is made.

An extraction with self_reported_confidence "high" that fails one of
these checks is still flagged — the model's own confidence is a signal,
not a verdict.
"""

from dataclasses import dataclass, field
from pathlib import Path
import csv

DATA_DIR = Path(__file__).parent / "data"

LINE_ITEM_TOLERANCE = 0.02          # EUR/USD - rounding only
PO_AMOUNT_TOLERANCE_ABS = 5.00      # flat allowance for small rounding/FX drift
PO_AMOUNT_TOLERANCE_PCT = 0.02      # 2% - larger allowance on bigger invoices


def _load_po_master() -> dict:
    pos = {}
    with open(DATA_DIR / "po_master.csv") as f:
        for row in csv.DictReader(f):
            pos[row["po_number"]] = {
                "entity": row["entity"],
                "vendor": row["vendor"],
                "amount": float(row["amount"]),
                "currency": row["currency"],
            }
    return pos


def _load_vendor_master() -> set:
    vendors = set()
    with open(DATA_DIR / "vendor_master.csv") as f:
        for row in csv.DictReader(f):
            if row["approved"].strip().upper() == "TRUE":
                vendors.add(row["vendor"])
    return vendors


@dataclass
class ValidationResult:
    invoice_id: str
    extracted: dict
    flags: list = field(default_factory=list)
    decision: str = "AUTO_APPROVED"  # AUTO_APPROVED | NEEDS_REVIEW | REJECTED

    def add_flag(self, code: str, detail: str, severity: str = "review"):
        self.flags.append({"code": code, "detail": detail, "severity": severity})


def validate_batch(extractions: dict[str, dict]) -> list[ValidationResult]:
    """
    extractions: {invoice_id (source filename) -> extracted dict}
    Runs cross-invoice checks (duplicates) as well as per-invoice checks,
    so order matters: duplicates can only be detected across the batch.
    """
    po_master = _load_po_master()
    vendor_master = _load_vendor_master()

    results = []
    seen_invoice_numbers = {}  # extracted invoice_number -> source file that had it first

    for invoice_id, data in extractions.items():
        result = ValidationResult(invoice_id=invoice_id, extracted=data)

        # --- 1. Duplicate check (by the invoice's own stated number, not filename) ---
        inv_num = data.get("invoice_number")
        if inv_num in seen_invoice_numbers:
            result.add_flag(
                "DUPLICATE_INVOICE_NUMBER",
                f"Invoice number '{inv_num}' already processed as "
                f"{seen_invoice_numbers[inv_num]}. Do not pay twice.",
                severity="reject",
            )
        else:
            seen_invoice_numbers[inv_num] = invoice_id

        # --- 2. Internal math check ---
        line_items = data.get("line_items") or []
        total = data.get("total_amount")
        if line_items and total is not None:
            line_sum = round(sum(li["amount"] for li in line_items), 2)
            if abs(line_sum - total) > LINE_ITEM_TOLERANCE:
                result.add_flag(
                    "LINE_ITEM_MISMATCH",
                    f"Line items sum to {line_sum:,.2f} but stated total is "
                    f"{total:,.2f} (diff {total - line_sum:+.2f}).",
                )

        # --- 3. PO checks ---
        po_ref = data.get("po_reference")
        if not po_ref:
            result.add_flag("MISSING_PO", "No PO reference found on the invoice.")
        elif po_ref not in po_master:
            result.add_flag("PO_NOT_FOUND", f"PO '{po_ref}' does not exist in PO master.")
        else:
            po = po_master[po_ref]

            if data.get("vendor") and data["vendor"] != po["vendor"]:
                result.add_flag(
                    "VENDOR_PO_MISMATCH",
                    f"Invoice vendor '{data['vendor']}' does not match PO vendor "
                    f"'{po['vendor']}' for {po_ref}.",
                )

            if data.get("currency") and data["currency"] != po["currency"]:
                result.add_flag(
                    "CURRENCY_MISMATCH",
                    f"Invoice is in {data['currency']} but PO {po_ref} was raised in "
                    f"{po['currency']}.",
                )

            if total is not None:
                tolerance = max(PO_AMOUNT_TOLERANCE_ABS, po["amount"] * PO_AMOUNT_TOLERANCE_PCT)
                diff = total - po["amount"]
                if abs(diff) > tolerance:
                    result.add_flag(
                        "AMOUNT_EXCEEDS_PO",
                        f"Invoice total {total:,.2f} vs PO amount {po['amount']:,.2f} "
                        f"(diff {diff:+,.2f}, tolerance ±{tolerance:,.2f}).",
                    )

        # --- 4. Vendor master check ---
        vendor = data.get("vendor")
        if vendor and vendor not in vendor_master:
            result.add_flag(
                "UNKNOWN_VENDOR",
                f"'{vendor}' is not in the approved vendor master. New vendor onboarding required.",
            )

        # --- 5. Model's own confidence, treated as a signal, not a verdict ---
        if data.get("self_reported_confidence") == "low":
            result.add_flag(
                "LOW_EXTRACTION_CONFIDENCE",
                "Claude flagged this extraction as low-confidence — worth a human glance "
                "even if no other check failed.",
            )

        # --- Decision ---
        if any(f["severity"] == "reject" for f in result.flags):
            result.decision = "REJECTED"
        elif result.flags:
            result.decision = "NEEDS_REVIEW"
        else:
            result.decision = "AUTO_APPROVED"

        results.append(result)

    return results
