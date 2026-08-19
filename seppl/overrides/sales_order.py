"""Sales Order → Sales Invoice, plus the Gate Pass's service charges.

The Gate Pass form's Create → Sales Invoice button does not map the Gate
Pass. It calls ERPNext's Sales Order → Sales Invoice mapper with
`frm.doc.sales_order` as the source (detox's `gate_pass.js`), so the
invoice is built from the SO's own lines and nothing typed on the Gate
Pass reaches it — service charges included.

Rather than change what that button maps, this wraps the mapper it calls.
Core `make_mapped_doc` resolves the mapper through
`frappe.override_whitelisted_method` (frappe/model/mapper.py), so
registering the override in hooks is enough to sit in front of it.

Which means this sits in front of EVERY Sales Order → Sales Invoice on the
site, including ones raised from the Sales Order form by people who have
never seen a Gate Pass. So it does nothing at all unless the caller
explicitly names a Gate Pass — see `requested_gate_pass`. Naming one is
what the "Gate Pass - Service Items" Client Script adds to the button.
"""

import frappe
from frappe.utils import flt

from erpnext.selling.doctype.sales_order.sales_order import (
	make_sales_invoice as _core_make_sales_invoice,
)

from seppl.overrides.gate_pass import service_rows


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, args=None, ignore_permissions=False):
	# Keyword args, and the same parameter order as the core mapper: it takes
	# (source_name, target_doc, args, ignore_permissions), so passing them
	# positionally in any other order lands `ignore_permissions` in `args` and
	# the whitelist type check rejects the bool.
	target = _core_make_sales_invoice(
		source_name,
		target_doc=target_doc,
		args=args,
		ignore_permissions=ignore_permissions,
	)
	gate_pass = (frappe.flags.args or {}).get("gate_pass")
	if not gate_pass:
		return target

	stamp_gate_pass_on_mapped_rows(target, gate_pass)
	add_service_charges(target, gate_pass)
	return target


def stamp_gate_pass_on_mapped_rows(target, gate_pass):
	source = frappe.db.get_value(
		"Gate Pass", gate_pass, ["manifest_no", "sales_order"], as_dict=True
	)
	if not source:
		return

	inward_date = frappe.db.get_value(
		"Gate Pass Item",
		{
			"parent": gate_pass,
			"parentfield": "items",
			"custom_waste_inward_date": ("is", "set"),
		},
		"custom_waste_inward_date",
	)
	for row in target.get("items") or []:
		# Never overwrite a row that already names its own Gate Pass.
		if row.get("custom_gate_pass"):
			continue
		row.custom_gate_pass = gate_pass
		if source.manifest_no:
			row.custom_manifest_no = source.manifest_no
		if inward_date:
			row.custom_waste_inward_date = inward_date


def add_service_charges(target, gate_pass):
	rows = service_rows(gate_pass)
	if not rows:
		return

	for row in rows:
		target.append("items", service_invoice_row(row, gate_pass))

	# The rows arrive after the mapper has already run these, so the new
	# ones would otherwise carry no income account, no tax template and no
	# share of the totals.
	target.flags.ignore_permissions = True
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")


def service_invoice_row(row, gate_pass):
	# `row` is a `Gate Pass Service Item` — its own child doctype, so the
	# fields have no `custom_` prefix. The Sales Invoice Item side still
	# does: those are Custom Fields on a standard doctype.
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
