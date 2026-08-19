"""Waste Inward date -> Gate Pass service items.

A service row is billed alongside the waste it was raised with, so it has
to carry the same Waste Inward date the waste rows do — the Sales Invoice
picker grid, the ZWR reports and the print formats all read
`waste_inward_posting_date` off the row.

detox fills that field on the waste table (`overrides.gate_pass.
populate_waste_inward_date_on_items`, on Gate Pass validate). That hook
loops `doc.items` by name, so it never reaches the service table — and by
the time a Waste Inward is submitted the Gate Pass is normally submitted
too and will not be re-saved anyway. Stamping from the Waste Inward's own
submit is what makes the date land at the moment it becomes known.

The write itself goes through `frappe.db.set_value` rather than a save:
the parent Gate Pass is submitted, so a normal save would be rejected.
"""

import frappe
from frappe.utils import getdate

from seppl.overrides.gate_pass import SERVICE_ITEM_DOCTYPE, SERVICE_ITEMS_FIELD


def on_submit(doc, method=None):
	stamp_inward_date_on_service_items(doc)


def stamp_inward_date_on_service_items(doc):
	"""Copy this Waste Inward's date onto its Gate Pass's service rows."""
	if not doc.get("gate_pass") or not doc.get("date"):
		return
	inward_date = getdate(doc.date)
	service_items = frappe.get_all(
		SERVICE_ITEM_DOCTYPE,
		filters={"parent": doc.gate_pass, "parentfield": SERVICE_ITEMS_FIELD},
		pluck="name",
	)
	for row in service_items:
		frappe.db.set_value(
			SERVICE_ITEM_DOCTYPE, row, "waste_inward_posting_date", inward_date,
			update_modified=False,
		)
