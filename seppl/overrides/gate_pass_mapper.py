"""Stamp the source Gate Pass onto every row pulled into a Sales Invoice.

Sales Invoice → Get Items From → Gate Pass opens a multi-select picker and
maps the chosen Gate Passes into the invoice. The mapper that does the work
lives in `detox_waste_management` and this app must not edit it, so SEPPL
hooks the layer above instead: ERPNext's picker posts to the core
whitelisted method `frappe.model.mapper.map_docs`, which loops the selected
source documents through the mapper one at a time. Overriding that method
(`override_whitelisted_methods` in hooks.py) puts us inside the loop, where
we still know which Gate Pass produced which rows — information the mapper's
return value alone no longer carries once several Gate Passes have been
merged into one invoice.

Every other mapping on the site (Sales Order → Delivery Note, Quotation →
Sales Order, …) is handed straight back to the core implementation.
"""

import json

import frappe
from frappe import _
from frappe.model.mapper import map_docs as _core_map_docs

GATE_PASS_TO_SALES_INVOICE = (
	"detox_waste_management.detox_waste_management.doctype.gate_pass.gate_pass.make_sales_invoice"
)


@frappe.whitelist()
def map_docs(
	method: str,
	source_names: str,
	target_doc: str | None = None,
	args: str | None = None,
):
	"""Core `map_docs`, plus a Gate Pass stamp on the rows it produces.

	Hints mirror what actually arrives over the wire — the picker's
	`frappe.call` JSON-encodes every argument, so `source_names` is a JSON
	array string and `target_doc` / `args` are JSON object strings. Direct
	Python callers may still pass a real list; the body tolerates both.
	"""
	if method != GATE_PASS_TO_SALES_INVOICE:
		return _core_map_docs(method, source_names, target_doc, args)

	mapper = frappe.get_attr(method)
	if mapper not in frappe.whitelisted:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if isinstance(source_names, str):
		source_names = json.loads(source_names)

	for source_name in source_names:
		mapper_args = (source_name, target_doc, json.loads(args)) if args else (source_name, target_doc)
		target_doc = mapper(*mapper_args)
		# Rows the previous iterations already claimed keep their own Gate
		# Pass; whatever is still blank was produced by THIS source.
		stamp_source_gate_pass(target_doc, source_name)

	return target_doc


def stamp_source_gate_pass(target_doc, gate_pass):
	"""Fill in `custom_gate_pass` wherever it is still blank.

	The header field keeps the FIRST Gate Pass of the pull — it can only
	hold one, and the single-Gate-Pass features downstream (Disposal
	Certificate auto-create) read it. The per-row field is the complete
	picture.
	"""
	if not target_doc or not gate_pass:
		return
	if not target_doc.get("custom_gate_pass"):
		target_doc.custom_gate_pass = gate_pass
	for row in target_doc.get("items") or []:
		if not row.get("custom_gate_pass"):
			row.custom_gate_pass = gate_pass
