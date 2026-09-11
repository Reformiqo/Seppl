from frappe.custom.doctype.custom_field.custom_field import create_custom_fields as _create_custom_fields


def create_custom_fields():
	_create_custom_fields(
		{
			# The Service Items table is priced off a Price List the way an
			# invoice row is; both fields sit directly above that table.
			"Gate Pass": [
				dict(fieldname="custom_price_list", fieldtype="Link",
				     label="Price List", options="Price List",
				     insert_after="items", allow_on_submit=1,
				     description="Rate card the Service Items are priced from."),
				dict(fieldname="custom_ignore_pricing_rule", fieldtype="Check",
				     label="Ignore Pricing Rule", insert_after="custom_price_list",
				     depends_on="custom_price_list", allow_on_submit=1),
			],
		},
		update=True,
	)
