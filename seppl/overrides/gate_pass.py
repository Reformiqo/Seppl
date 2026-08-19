import frappe

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
