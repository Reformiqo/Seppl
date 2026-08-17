"""Backfill blank PANs on Tax Withholding Entry so split TDS histories re-merge.

THE BUG
-------
ERPNext v16 checks the TDS threshold **PAN-wise, not supplier-name-wise**.
In `erpnext/accounts/doctype/tax_withholding_entry/tax_withholding_entry.py`,
`TaxWithholdingController._base_threshold_query` ends with:

    query = (
        query.where(entry.tax_id == category.tax_id)   # party HAS a PAN
        if category.tax_id
        else query.where(entry.party == self.party)    # party has none
    )

So when a Supplier was invoiced BEFORE its PAN was filled in, those Tax
Withholding Entry rows were written with `tax_id = NULL`. Once the PAN
was added to the Supplier master, every later invoice got stamped with
the PAN and the query switched to the first branch -- which can no
longer see the older NULL rows.

The supplier ends up with two disjoint histories under one name. The
cumulative purchase value already accumulated is not recognised, the
threshold counter effectively restarts from zero, and TDS stops being
deducted even though the Rs 50,00,000 limit was already crossed. It is
completely silent: no error, no warning, no message on the invoice,
because from the engine's point of view this is simply a party it has
never withheld against before.

For a category with `tax_on_excess_amount` set, the damage surfaces via
`_get_unused_threshold`, which reuses the very same query:

    return category.cumulative_threshold - result.get("Settled", 0)

Missing history makes `Settled` too small, `unused_threshold` comes back
too large, and the next invoices get exempted all over again.

THE `pan` vs `tax_id` TRAP
--------------------------
`category.tax_id` is resolved by `get_tax_id_for_party`, which
india_compliance overrides (see
`india_compliance/income_tax_india/overrides/tax_withholding_category.py`)
to return the **`pan`** field on Supplier / Customer -- NOT the
`tax_id` (GSTIN) field of the same name:

    def get_tax_id_for_party(party_type, party):
        if party_type in ("Customer", "Supplier"):
            return frappe.db.get_value(party_type, party, "pan")
        return ""

Sourcing this heal from `Supplier.tax_id` would therefore write GSTINs
into a column the threshold engine compares against PANs -- it would
look fixed and still be broken. We read `pan`.

SAFETY PROFILE
--------------
  * ONLY the `tax_id` column is written. Never an amount, rate, status,
    docstatus, date, voucher link, or anything participating in a GL
    entry. TDS already deducted is not recomputed and no accounting
    entry is touched.

  * `update_modified=False` -- the parent Purchase Invoice's `modified`
    timestamp is left alone, so this does not surface as an edit on the
    invoice or trip optimistic locking on anyone's open form.

  * Parties whose master still has NO PAN are skipped. Their rows are
    *correctly* blank -- the engine falls back to the
    `entry.party == self.party` branch, which already aggregates their
    history properly. Writing anything there would break a working case.

  * Rows that already carry a PAN are never overwritten, even when it
    disagrees with the master. Those are reported as conflicts for a
    human to look at: a PAN changed or corrected after the fact is a
    different problem with different tax consequences.

  * Cancelled rows (docstatus=2) are healed too. Every threshold query
    filters `docstatus == 1`, so this cannot move a number; it just
    keeps the column consistent for the Tax Withholding Details report,
    which displays `tax_id` directly.

  * Rows with no party at all are skipped (a legacy zero-amount orphan
    row exists on at least one site).

  * Idempotent -- re-running finds nothing to repair.

NOTE ON RECURRENCE
------------------
This is a point-in-time heal. It fixes the rows that exist when it runs.
Because ERPNext stamps `tax_id` at submit time from the master, the same
split re-forms for any supplier that is invoiced now and has its PAN
added later. Re-run this patch after such a backfill of Supplier PANs:

    bench --site <site> execute \
      seppl.patches.backfill_twe_blank_pan.execute
"""

import frappe

DOCTYPE = "Tax Withholding Entry"

# Supplier only. Customer rows are deliberately out of scope -- the same
# split can form there for TCS, but nothing has reported it and a heal
# that rewrites customer tax identifiers unasked is not worth the risk.
PARTY_TYPE = "Supplier"


def execute():
    if not frappe.db.table_exists(DOCTYPE):
        return

    if not frappe.db.has_column(PARTY_TYPE, "pan"):
        # india_compliance not installed on this site.
        return

    repaired = {}
    conflicts = []
    skipped_no_master_pan = 0

    # ---- rows to heal: blank tax_id ---------------------------------
    blank_rows = frappe.get_all(
        DOCTYPE,
        filters={"party_type": PARTY_TYPE, "tax_id": ("in", ("", None))},
        fields=["name", "party"],
    )

    # ---- rows to audit: tax_id disagrees with the master ------------
    stamped_rows = frappe.get_all(
        DOCTYPE,
        filters={"party_type": PARTY_TYPE, "tax_id": ("not in", ("", None))},
        fields=["name", "party", "tax_id", "docstatus"],
    )

    # One master lookup per distinct supplier rather than per row.
    suppliers = {r.party for r in blank_rows + stamped_rows if r.party}
    pan_map = {
        s: (frappe.db.get_value(PARTY_TYPE, s, "pan") or "").strip()
        for s in suppliers
    }

    for row in blank_rows:
        if not row.party:
            continue

        pan = pan_map.get(row.party)
        if not pan:
            # Master has no PAN either. The engine's party-name fallback
            # already aggregates this supplier correctly.
            skipped_no_master_pan += 1
            continue

        # tax_id ONLY, and without touching the parent's timestamp.
        frappe.db.set_value(DOCTYPE, row.name, "tax_id", pan, update_modified=False)
        key = (row.party, pan)
        repaired[key] = repaired.get(key, 0) + 1

    for row in stamped_rows:
        master_pan = pan_map.get(row.party)
        if master_pan and master_pan != (row.tax_id or "").strip():
            conflicts.append(
                f"  {row.name} | Supplier {row.party} | "
                f"row PAN {row.tax_id!r} != master PAN {master_pan!r} | "
                f"docstatus {row.docstatus}"
            )

    if repaired:
        frappe.db.commit()
        total = sum(repaired.values())
        print(
            f"[TWE-PAN] linked {total} blank-PAN tax withholding row(s) to "
            f"their master PAN across {len(repaired)} supplier(s):"
        )
        for (supplier, pan), count in sorted(repaired.items()):
            print(f"[TWE-PAN]   {supplier} -> {pan}: {count} row(s)")
    else:
        print("[TWE-PAN] no blank-PAN tax withholding rows to repair.")

    if skipped_no_master_pan:
        print(
            f"[TWE-PAN] skipped {skipped_no_master_pan} blank row(s) whose "
            f"Supplier master has no PAN either -- these already aggregate "
            f"correctly via the party-name fallback."
        )

    # Rows disagreeing with the master are NOT rewritten -- different
    # problem, different tax consequences. Surface them for a human.
    if conflicts:
        detail = "\n".join(conflicts)
        print(
            f"[TWE-PAN] WARNING: {len(conflicts)} row(s) carry a PAN that "
            f"differs from the party master. Left untouched:\n{detail}"
        )
        frappe.log_error(
            title="TWE PAN backfill: rows disagree with master PAN",
            message=detail,
        )
