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
def make_sales_invoice(source_name, target_doc=None, ignore_permissions=False, args=None):
	target = _core_make_sales_invoice(source_name, target_doc, ignore_permissions, args)
	gate_pass = (frappe.flags.args or {}).get("gate_pass")
	if not gate_pass:
		return target

	add_service_charges(target, gate_pass)
	return target


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
	print(row, "rows")

	qty = flt(row.custom_confirm_qty) or flt(row.qty)
	return {
		"item_code": row.item_code,
		"qty": qty,
		"uom": row.uom,
		"rate": row.rate,
		"amount": qty * flt(row.rate),
		# What makes `seppl.overrides.sales_invoice` back-link the Gate Pass
		# on save, which is also what keeps it out of the next invoice.
		"custom_gate_pass": gate_pass,
		"custom_manifest_no": row.custom_manifest_no,
		"custom_waste_inward_date" : row.custom_waste_inward_date
	}
