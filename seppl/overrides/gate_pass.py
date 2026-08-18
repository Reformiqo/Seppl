import frappe

SERVICE_ITEMS_FIELD = "custom_service_items"


def service_rows(gate_pass, fields=("name", "item_code", "qty", "custom_confirm_qty", "uom", "rate", "custom_waste_inward_date")):
	"""A saved Gate Pass's service rows.

	Filtered on `parentfield`, not `parenttype`: `parenttype` is "Gate
	Pass" for BOTH tables — they share the `Gate Pass Item` child doctype
	— so it is the fieldname that tells the service rows apart from the
	waste rows.
	"""
	return frappe.get_all(
		"Gate Pass Item",
		filters={"parent": gate_pass, "parentfield": SERVICE_ITEMS_FIELD},
		fields=list(fields),
		order_by="idx",
	)
