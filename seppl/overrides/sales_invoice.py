"""Sales Invoice ↔ Gate Pass back-link.

Once an invoice names its Gate Passes (header field, or per-row
`custom_gate_pass` stamped by `seppl.overrides.gate_pass_mapper`), the Gate
Passes must point back at the invoice: `Gate Pass.sales_invoice`. That link
is what the "Get Items From → Gate Pass" picker filters on — it only offers
Gate Passes whose `sales_invoice` is empty — so it is also what stops the
same Gate Pass being billed twice.

Wired on `on_update`, which Frappe runs on a draft save AND immediately
before `on_submit`, so a saved draft already claims its Gate Passes instead
of leaving them up for grabs until someone submits.
"""

import frappe
from frappe import _


def before_validate(doc, method=None):
	backfill_gate_pass_from_manifest(doc)


def on_update(doc, method=None):
	link_invoice_to_gate_pass(doc)


def gate_passes_on_invoice(doc):
	"""Every Gate Pass this invoice bills, in first-seen order.

	Two sources, because the header can only name ONE Gate Pass while the
	picker aggregates many:
	  • doc.custom_gate_pass          — header link (first Gate Pass of the
	                                    pull, or one picked by hand)
	  • doc.items[].custom_gate_pass  — per-row link
	"""
	names, seen = [], set()
	candidates = [doc.get("custom_gate_pass")]
	candidates += [row.get("custom_gate_pass") for row in (doc.get("items") or [])]
	for gate_pass in candidates:
		if gate_pass and gate_pass not in seen:
			seen.add(gate_pass)
			names.append(gate_pass)
	return names


def invoice_is_dead(sales_invoice):
	"""True when an existing back-link points at nothing worth protecting —
	a deleted invoice, or a cancelled one. Finance re-bills a Gate Pass
	after cancelling its invoice, so a cancelled stub must not hold it.
	"""
	if not sales_invoice:
		return True
	docstatus = frappe.db.get_value("Sales Invoice", sales_invoice, "docstatus")
	return docstatus is None or docstatus == 2


def link_invoice_to_gate_pass(doc, method=None):
	"""Point every Gate Pass billed on this invoice back at it.

	Never raises: a back-link is bookkeeping and must not block a save or a
	submit. A Gate Pass already claimed by a DIFFERENT live invoice is left
	alone and reported, so the operator sees the clash instead of it being
	silently overwritten.
	"""
	invoice_gate_passes = gate_passes_on_invoice(doc)
	# An amend inherits the cancelled invoice's links; treat that value as
	# free rather than as a clash.
	releasable = {None, "", doc.name, doc.get("amended_from")}
	claimed = []

	for gate_pass in invoice_gate_passes:
		current = frappe.db.get_value("Gate Pass", gate_pass, "sales_invoice")
		if current not in releasable and not invoice_is_dead(current):
			claimed.append((gate_pass, current))
			continue
		if current != doc.name:
			frappe.db.set_value("Gate Pass", gate_pass, "sales_invoice", doc.name)

	# Rows dropped from a draft must release their Gate Pass again,
	# otherwise it stays invisible to the picker forever. Skipped during
	# insert — nothing can already point at a name generated moments ago,
	# and this runs on every Sales Invoice save.
	if not doc.get("__islocal") and not (doc.flags or {}).get("in_insert"):
		for stale in frappe.get_all("Gate Pass", filters={"sales_invoice": doc.name}, pluck="name"):
			if stale not in invoice_gate_passes:
				frappe.db.set_value("Gate Pass", stale, "sales_invoice", None)

	if claimed:
		frappe.msgprint(
			_(
				"These Gate Passes are already billed on another Sales "
				"Invoice and were left linked to it: {0}"
			).format(", ".join("{0} → {1}".format(gp, si) for gp, si in claimed)),
			indicator="orange",
		)


def backfill_gate_pass_from_manifest(doc):
	"""Safety net for rows that carry a Manifest No but no Gate Pass.

	The picker normally stamps the Gate Pass as it maps (see
	`seppl.overrides.gate_pass_mapper`). This covers the two cases it
	can't: invoices created before that hook existed, and an ERPNext
	release that routes the picker through something other than
	`frappe.model.mapper.map_docs`.

	Deliberately conservative — it only fills a BLANK field, and only when
	the manifest number resolves to exactly one submitted Gate Pass for
	this customer. An ambiguous manifest is left blank rather than guessed.
	"""
	if not doc.get("customer") or not frappe.db.exists("DocType", "Gate Pass"):
		return

	for row in doc.get("items") or []:
		manifest_no = row.get("custom_manifest_no")
		if row.get("custom_gate_pass") or not manifest_no:
			continue
		matches = frappe.get_all(
			"Gate Pass",
			filters={
				"docstatus": 1,
				"manifest_no": manifest_no,
				"customer": doc.customer,
				"transaction_type": "Inbound (Waste Receipt)",
			},
			pluck="name",
			limit=2,
		)
		if len(matches) == 1:
			row.custom_gate_pass = matches[0]


# ----------------------------------------------------------------------
# ABP2-I406 — multi-project / multi-cost-centre invoicing
# ----------------------------------------------------------------------
def validate_multi_project_mapping(doc, method=None):
	"""One invoice, many Sub Projects — BRD §3.2, FR-01 … FR-07.

	Most of what the BRD asks for is already in ERPNext and needs no code:
	`Sales Invoice Item` carries its own `project` and `cost_center`
	(mandatory), and the income GL entry is written per line against
	`item.cost_center` / `item.project`. So the revenue split by line
	(FR-06) is native — what was missing is the hierarchy that decides
	WHICH projects may appear together on one invoice.

	This adds that, and nothing more:

	  FR-01  a Group Project on the header, and it must really be one
	  FR-02  every line names a Sub Project
	  FR-03  each line carries its Group Project, stamped from the header
	  FR-07  blank Sub Project or Cost Centre blocks the invoice
	  §3.3   every line's Sub Project belongs to the header's Group Project

	Backward compatibility (NFR) is the reason for the early return: an
	invoice that names no Group Project and no Sub Project is an ordinary
	single-project invoice and is left completely alone.
	"""
	from seppl.overrides.project import group_project_of, is_group_project

	rows = doc.get("items") or []
	group_project = doc.get("custom_group_project")

	# One lookup per distinct project, not one per row (NFR — performance).
	groups = {}
	for row in rows:
		project = row.get("project")
		if project and project not in groups:
			groups[project] = group_project_of(project)

	sub_project_rows = [r for r in rows if groups.get(r.get("project"))]

	if not group_project and not sub_project_rows:
		return

	if not group_project:
		# FR-01 — a line already names a Sub Project, so the header has to
		# say which Group Project this invoice is for.
		row = sub_project_rows[0]
		frappe.throw(
			_(
				"Row #{0}: {1} is a Sub Project of Group Project {2}. Select "
				"that Group Project on the invoice header before billing it."
			).format(row.idx, row.project, groups[row.project]),
			title=_("Group Project required"),
		)

	if not is_group_project(group_project):
		frappe.throw(
			_(
				"{0} is not a Group Project. Only a project marked Is Group "
				"Project can be selected here."
			).format(group_project),
			title=_("Not a Group Project"),
		)

	# The header Project is the single-project mode: it feeds every line that
	# has no project of its own, and it is what the ABP2-I273 script filters
	# the line Cost Centre lookup by. Mixing the two modes is what makes a
	# multi-project invoice post to the wrong cost centres.
	if doc.get("project"):
		frappe.throw(
			_(
				"This invoice uses Group Project {0}, so each line carries its "
				"own Sub Project. Clear the Project field on the header — it "
				"applies to single-project invoices only."
			).format(group_project),
			title=_("Header Project not allowed"),
		)

	for row in rows:
		# FR-07 (b) and (c)
		if not row.get("project"):
			frappe.throw(
				_("Row #{0}: Sub Project is required on every line of a multi-project invoice.").format(row.idx),
				title=_("Sub Project required"),
			)
		if not row.get("cost_center"):
			frappe.throw(
				_("Row #{0}: Cost Centre is required on every line of a multi-project invoice.").format(row.idx),
				title=_("Cost Centre required"),
			)

		row_group = groups.get(row.project)
		if not row_group:
			frappe.throw(
				_(
					"Row #{0}: {1} is not a Sub Project. Open it and set its "
					"Group Project to {2}, or pick a Sub Project that already "
					"belongs to {2}."
				).format(row.idx, row.project, group_project),
				title=_("Not a Sub Project"),
			)

		# §3.3 — one invoice, one Group Project.
		if row_group != group_project:
			frappe.throw(
				_(
					"Row #{0}: {1} belongs to Group Project {2}, but this "
					"invoice is for {3}. Sub Projects from different Group "
					"Projects cannot share an invoice — raise a separate "
					"invoice for {2}."
				).format(row.idx, row.project, row_group, group_project),
				title=_("Mixed Group Projects"),
			)

		# FR-03 — the line's Group Project is inherited, never typed.
		row.custom_group_project = group_project
