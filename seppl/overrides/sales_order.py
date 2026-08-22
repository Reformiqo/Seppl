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

from erpnext.selling.doctype.sales_order.sales_order import (
	make_sales_invoice as _core_make_sales_invoice,
)

from seppl.overrides.gate_pass import (
	append_service_charges,
	recalculate,
	service_invoice_row,  # noqa: F401  (re-exported: imported from here historically)
)


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, args=None, ignore_permissions=False):
	target = _core_make_sales_invoice(
		source_name,
		target_doc=target_doc,
		args=args,
		ignore_permissions=ignore_permissions,
	)
	gate_pass = requested_gate_pass(source_name)
	if not gate_pass:
		return target

	stamp_gate_pass_on_mapped_rows(target, gate_pass)
	add_service_charges(target, gate_pass)
	return target


def requested_gate_pass(sales_order):
	"""The Gate Pass the caller named, once it has earned being trusted.

	`None` — meaning "behave exactly like core" — unless a Gate Pass was
	named AND it survives being re-checked against the database. The name
	arrives from the browser, so nothing about it is taken on faith:

	  • it must belong to THIS Sales Order. Billing another order's
	    charges here would be worse than billing none.
	  • it must not already name a Sales Invoice. Without that, every
	    later invoice raised for the Sales Order re-bills the same
	    charge. Blunt truthiness on purpose — the same check detox's Gate
	    Pass mapper makes before it will map a Gate Pass at all.
	"""
	gate_pass = (frappe.flags.args or {}).get("gate_pass")
	if not gate_pass:
		return None

	source = frappe.db.get_value(
		"Gate Pass", gate_pass, ["sales_order", "sales_invoice"], as_dict=True
	)
	if not source or source.sales_order != sales_order or source.sales_invoice:
		return None
	return gate_pass


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
	"""The Gate Pass's service rows, appended and totalled into `target`.

	The single-Gate-Pass case. The picker path appends for several Gate
	Passes before totalling once — see `seppl.overrides.gate_pass_mapper`.
	"""
	if append_service_charges(target, gate_pass):
		recalculate(target)
