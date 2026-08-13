"""Custom fields owned by the SEPPL app.

Runs on install and on every `bench migrate`, so a fresh site ends up with
the same schema as the one the fixtures were exported from. Idempotent —
`create_custom_fields(update=True)` updates an existing field in place
rather than erroring.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import (
	create_custom_fields as _create_custom_fields,
)

MODULE = "Seppl"


def after_install():
	create_custom_fields()


def after_migrate():
	create_custom_fields()


def create_custom_fields():
	"""Sales Invoice Item → Gate Pass.

	"Get Items From → Gate Pass" pulls rows from one or MANY Gate Passes
	into a single Sales Invoice, so the header link
	(`Sales Invoice.custom_gate_pass`) can only ever name one of them.
	This per-row field is the complete record of which Gate Pass each
	billed line came from, and it is what
	`seppl.overrides.sales_invoice.link_invoice_to_gate_pass` reads back
	to stamp `Gate Pass.sales_invoice`.

	Skipped when the Gate Pass doctype isn't on the site — the Link would
	point at nothing.
	"""
	if not frappe.db.exists("DocType", "Gate Pass"):
		print("seppl.setup: Gate Pass doctype absent — skipping custom fields")
		return

	_create_custom_fields(
		{
			"Sales Invoice Item": [
				dict(
					fieldname="custom_gate_pass",
					fieldtype="Link",
					label="Gate Pass",
					options="Gate Pass",
					insert_after="custom_waste_inward_date",
					read_only=1,
					in_list_view=1,
					module=MODULE,
					description=(
						"Source Gate Pass for this row — stamped when the "
						"invoice is built via Get Items From → Gate Pass."
					),
				),
			],
		},
		update=True,
	)
