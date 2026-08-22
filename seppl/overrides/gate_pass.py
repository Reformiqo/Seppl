import frappe
from frappe.utils import flt

SERVICE_ITEMS_FIELD = "custom_service_items"
SERVICE_ITEM_DOCTYPE = "Gate Pass Service Item"

SERVICE_ROW_FIELDS = (
	"name",
	"item_code",
	"qty",
	"confirm_qty",
	"uom",
	"rate",
	"waste_inward_posting_date",
	"manifest_no",
)


def service_rows(gate_pass, fields=SERVICE_ROW_FIELDS):
	"""A saved Gate Pass's service rows.

	The service table has its own child doctype now — `Gate Pass Service
	Item` — instead of sharing `Gate Pass Item` with the waste rows, so
	its fields carry no `custom_` prefix and the doctype alone already
	tells the two tables apart. `parentfield` stays in the filter anyway:
	it costs nothing and keeps the query correct if the doctype is ever
	reused for a second table on the same parent.
	"""
	return frappe.get_all(
		SERVICE_ITEM_DOCTYPE,
		filters={"parent": gate_pass, "parentfield": SERVICE_ITEMS_FIELD},
		fields=list(fields),
		order_by="idx",
	)


def service_invoice_row(row, gate_pass):
	"""One `Gate Pass Service Item` as a Sales Invoice Item payload.

	`row` is a `Gate Pass Service Item` — its own child doctype, so the
	fields have no `custom_` prefix. The Sales Invoice Item side still
	does: those are Custom Fields on a standard doctype.

	Confirm Qty wins when it is set, mirroring what detox's waste-row
	mapper does: the qty typed at the gate is what arrived, the confirmed
	qty is what finance bills.
	"""
	qty = flt(row.confirm_qty) or flt(row.qty)
	return {
		"item_code": row.item_code,
		"qty": qty,
		"uom": row.uom,
		"rate": row.rate,
		"amount": qty * flt(row.rate),
		# What makes `seppl.overrides.sales_invoice` back-link the Gate Pass
		# on save, which is also what keeps it out of the next invoice.
		"custom_gate_pass": gate_pass,
		"custom_manifest_no": row.manifest_no,
		"custom_waste_inward_date": row.waste_inward_posting_date,
	}


def append_service_charges(target, gate_pass):
	"""Append a Gate Pass's service rows to an invoice. No recompute.

	Split from the recompute so a caller mapping SEVERAL Gate Passes into
	one invoice (the "Get Items From → Gate Pass" picker) can append for
	each of them and total the invoice once at the end. Returns how many
	rows were added, so that caller knows whether a recompute is owed.
	"""
	rows = service_rows(gate_pass)
	for row in rows:
		target.append("items", service_invoice_row(row, gate_pass))
	return len(rows)


def recalculate(target):
	"""Re-run what the mapper already ran before the rows were appended.

	Without this the appended rows carry no income account, no tax
	template and no share of the totals — the charge is on the invoice
	but invisible in what it bills.
	"""
	target.flags.ignore_permissions = True
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")
