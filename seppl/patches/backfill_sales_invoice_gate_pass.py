"""Backfill the Sales Invoice ↔ Gate Pass links on existing documents.

New invoices get `Sales Invoice Item.custom_gate_pass` stamped by
`seppl.overrides.gate_pass_mapper` and `Gate Pass.sales_invoice` written
back by `seppl.overrides.sales_invoice`. Invoices raised before that
existed have neither, and nothing will re-save them.

Manifest No is the bridge: the mapper copies `Gate Pass.manifest_no` onto
every row it produces as `Sales Invoice Item.custom_manifest_no`, so an
existing row can be traced back to its Gate Pass through that number.

Deliberately conservative — a wrong link here is worse than a missing one,
because `Gate Pass.sales_invoice` is what the picker filters on and a bad
value hides a Gate Pass from billing:

  * Only fills BLANK fields. Re-runnable; never overwrites. That is also
    what makes `undo` possible without storing old values.
  * Only SUBMITTED Gate Passes are candidates. Measured on the live data:
    this excludes 6 Gate Passes, 3 of which share a manifest number with a
    submitted one — so the filter removes real ambiguity rather than
    matches.
  * Only INBOUND Gate Passes are candidates. Outbound is a vendor dispatch
    that belongs on `Gate Pass.purchase_invoice`, and the picker's mapper
    hard-throws on it. On the live data every Gate Pass is Inbound, so this
    filter currently excludes nothing — it is here to stop a wrong link if
    Outbound Gate Passes ever appear.
  * Cancelled invoices are skipped, so a cancelled stub can't claim a
    Gate Pass away from its live amendment.
  * A manifest that resolves to more than one Gate Pass, or to one
    belonging to a different customer, is left alone and reported.
  * A Gate Pass already linked to a live invoice is never re-pointed.

Anything skipped lands in an Error Log titled "Gate Pass backfill" so it
can be reviewed and fixed by hand.

Dry run before migrating a production site:

    bench --site <site> execute \\
        seppl.patches.backfill_sales_invoice_gate_pass.preview
"""

import json

import frappe

from seppl.overrides.sales_invoice import invoice_is_dead

GATE_PASS = "Gate Pass"
INBOUND = "Inbound (Waste Receipt)"
LOG_TITLE = "Gate Pass backfill"
UNDO_TITLE = "Gate Pass backfill undo"


def execute():
	run(apply=True)


def preview():
	"""Report what `execute` would change, without writing anything."""
	return run(apply=False)


def undo():
	"""Reverse the last apply.

	Every field this patch writes was BLANK beforehand — that is enforced by
	the scan — so undoing needs no old values, only the list of documents
	touched. `run` stores that list as JSON in an Error Log titled
	"Gate Pass backfill undo".

	    bench --site <site> execute \\
	        seppl.patches.backfill_sales_invoice_gate_pass.undo

	Note that Log Settings clears Error Logs after a retention period; keep
	a copy of the audit if the undo window needs to outlive it.
	"""
	audit = frappe.db.get_value(
		"Error Log",
		{"method": UNDO_TITLE},
		["name", "error"],
		order_by="creation desc",
		as_dict=True,
	)
	if not audit:
		print(f"{UNDO_TITLE}: no audit found — nothing to undo")
		return {}

	touched = json.loads(audit.error)
	for name in touched.get("sales_invoice_items", []):
		frappe.db.set_value("Sales Invoice Item", name, "custom_gate_pass", None, update_modified=False)
	for name in touched.get("sales_invoices", []):
		frappe.db.set_value("Sales Invoice", name, "custom_gate_pass", None, update_modified=False)
	for name in touched.get("gate_passes", []):
		frappe.db.set_value(GATE_PASS, name, "sales_invoice", None, update_modified=False)
	frappe.db.commit()

	reverted = {key: len(value) for key, value in touched.items()}
	print(f"{UNDO_TITLE}: reverted {reverted} (from Error Log {audit.name})")
	return reverted


def choose_gate_pass(candidates, customer):
	"""Pick the one Gate Pass a manifest number belongs to.

	`candidates` are the submitted Inbound Gate Passes carrying that
	manifest number. Returns (gate_pass_name, reason) — the name is None
	whenever the answer isn't unambiguous.
	"""
	if not candidates:
		return None, "unmatched"

	if len(candidates) > 1:
		# Narrow by customer before giving up — two sites could in
		# principle reuse a manifest number.
		candidates = [c for c in candidates if c.get("customer") == customer]
		if len(candidates) != 1:
			return None, "ambiguous"

	gate_pass = candidates[0]
	# A blank customer on the Gate Pass is old data, not a contradiction.
	if gate_pass.get("customer") and gate_pass["customer"] != customer:
		return None, "customer_mismatch"
	return gate_pass["name"], "ok"


def schema_ready():
	return (
		frappe.db.exists("DocType", GATE_PASS)
		and frappe.db.has_column("Sales Invoice Item", "custom_manifest_no")
		and frappe.db.has_column("Sales Invoice Item", "custom_gate_pass")
	)


def unlinked_rows():
	"""Live Sales Invoice rows that carry a Manifest No but no Gate Pass."""
	return frappe.db.sql(
		"""
		SELECT sii.name AS row_name, sii.parent AS invoice, sii.idx AS idx,
		       sii.custom_manifest_no AS manifest_no, si.customer AS customer
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.parenttype = 'Sales Invoice'
		  AND COALESCE(sii.custom_manifest_no, '') != ''
		  AND COALESCE(sii.custom_gate_pass, '') = ''
		  AND si.docstatus < 2
		ORDER BY sii.parent, sii.idx
		""",
		as_dict=True,
	)


def run(apply=True):
	if not schema_ready():
		print(f"{LOG_TITLE}: Gate Pass / manifest fields absent on this site — skipped")
		return {}

	rows = unlinked_rows()
	cache, skipped = {}, []
	row_updates = []
	header_choice = {}
	gate_pass_invoices = {}

	for row in rows:
		key = (row.manifest_no, row.customer)
		if key not in cache:
			candidates = frappe.get_all(
				GATE_PASS,
				filters={
					"manifest_no": row.manifest_no,
					"docstatus": 1,
					"transaction_type": INBOUND,
				},
				fields=["name", "customer"],
				limit=5,
			)
			cache[key] = choose_gate_pass(candidates, row.customer)

		gate_pass, reason = cache[key]
		if not gate_pass:
			skipped.append(f"{row.invoice} row {row.idx}: manifest {row.manifest_no} — {reason}")
			continue

		row_updates.append((row.row_name, gate_pass))
		header_choice.setdefault(row.invoice, gate_pass)
		gate_pass_invoices.setdefault(gate_pass, set()).add(row.invoice)

	# Gate Pass → Sales Invoice, applying the same guards as the runtime
	# hook so the patch can never steal a Gate Pass from a live invoice.
	gate_pass_updates = []
	for gate_pass, invoices in sorted(gate_pass_invoices.items()):
		if len(invoices) > 1:
			skipped.append(
				f"{gate_pass}: manifest appears on {len(invoices)} live invoices "
				f"({', '.join(sorted(invoices))}) — not linked"
			)
			continue
		invoice = invoices.pop()
		current = frappe.db.get_value(GATE_PASS, gate_pass, "sales_invoice")
		if current == invoice:
			continue
		if current and not invoice_is_dead(current):
			skipped.append(f"{gate_pass}: already billed on live invoice {current} — left alone")
			continue
		gate_pass_updates.append((gate_pass, invoice))

	# Header link, for parity with what the mapper does on new invoices.
	header_updates = [
		(invoice, gate_pass)
		for invoice, gate_pass in header_choice.items()
		if not frappe.db.get_value("Sales Invoice", invoice, "custom_gate_pass")
	]

	summary = {
		"rows_scanned": len(rows),
		"item_rows": len(row_updates),
		"invoice_headers": len(header_updates),
		"gate_passes": len(gate_pass_updates),
		"skipped": len(skipped),
	}

	if not apply:
		print(f"{LOG_TITLE} (preview, nothing written): {summary}")
		for line in skipped[:50]:
			print(f"  skipped — {line}")
		if len(skipped) > 50:
			print(f"  ... and {len(skipped) - 50} more")
		return summary

	for row_name, gate_pass in row_updates:
		frappe.db.set_value(
			"Sales Invoice Item", row_name, "custom_gate_pass", gate_pass, update_modified=False
		)
	for invoice, gate_pass in header_updates:
		frappe.db.set_value("Sales Invoice", invoice, "custom_gate_pass", gate_pass, update_modified=False)
	for gate_pass, invoice in gate_pass_updates:
		frappe.db.set_value(GATE_PASS, gate_pass, "sales_invoice", invoice, update_modified=False)

	# Undo trail. Every field written above was blank beforehand, so the
	# document names alone are enough to put things back — see `undo`.
	frappe.log_error(
		title=UNDO_TITLE,
		message=json.dumps(
			{
				"sales_invoice_items": [name for name, _gp in row_updates],
				"sales_invoices": [name for name, _gp in header_updates],
				"gate_passes": [name for name, _si in gate_pass_updates],
			},
			indent=1,
		),
	)
	frappe.db.commit()

	print(f"{LOG_TITLE}: {summary}")
	if skipped:
		frappe.log_error(
			title=LOG_TITLE,
			message=(f"{summary}\n\nLeft for manual review:\n\n" + "\n".join(skipped)),
		)
	return summary
