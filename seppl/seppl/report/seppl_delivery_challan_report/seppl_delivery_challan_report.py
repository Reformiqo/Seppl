"""SEPPL Delivery Challan Report.

Same logic as the Erpera Reports "Delivery Challan Report", plus
Project ID, Project Name and E-Way Bill columns.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, nowdate, today

_DOCUMENT_TYPE_CONDITIONS = {
	"Invoice": "(si.is_return = 0 AND si.is_debit_note = 0)",
	"Credit Note": "(si.is_return = 1 AND si.is_debit_note = 0)",
	"Debit Note": "si.is_debit_note = 1",
}

_TOTALLABLE_FIELDTYPES = {"Float", "Int", "Currency", "Percent"}
_SKIP_TOTAL_FIELDTYPES = {"Percent"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_apply_defaults(filters)
	_validate(filters)
	columns = get_columns()
	data = get_data(filters)
	_append_total_row(columns, data)
	return columns, data


def _append_total_row(columns, data):
	if not data:
		return
	totals = {}
	for c in columns:
		ft = c.get("fieldtype")
		if ft in _TOTALLABLE_FIELDTYPES and ft not in _SKIP_TOTAL_FIELDTYPES:
			totals[c["fieldname"]] = sum(flt(r.get(c["fieldname"]) or 0) for r in data)

	label_field = None
	for c in columns:
		if c.get("fieldtype") not in _TOTALLABLE_FIELDTYPES and c.get("fieldtype") not in (
			"Link",
			"Date",
		):
			label_field = c["fieldname"]
			break

	total_row = dict.fromkeys((c["fieldname"] for c in columns), None)
	total_row.update(totals)
	total_row[label_field or columns[0]["fieldname"]] = _("TOTAL")
	total_row["is_total_row"] = 1
	data.append(total_row)


# ---------------------------------------------------------------------------
# Defaults + validation
# ---------------------------------------------------------------------------


def _apply_defaults(filters):
	if not filters.get("company"):
		filters.company = frappe.defaults.get_user_default("Company")
	if not filters.get("from_date"):
		filters.from_date = str(get_first_day(nowdate()))
	if not filters.get("to_date"):
		filters.to_date = today()
	if not filters.get("invoice_status"):
		filters.invoice_status = "All"


def _validate(filters):
	if not filters.get("company"):
		frappe.throw(_("Company is mandatory"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are mandatory"))
	if getdate(filters.to_date) < getdate(filters.from_date):
		frappe.throw(_("To Date must be on or after From Date"))
	if filters.invoice_status not in ("All", "Billed", "Unbilled"):
		frappe.throw(_("Invoice Status must be one of: All, Billed, Unbilled"))
	if filters.get("document_type") and filters.document_type not in _DOCUMENT_TYPE_CONDITIONS:
		frappe.throw(
			_("Document Type must be one of: {0}").format(", ".join(_DOCUMENT_TYPE_CONDITIONS))
		)


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


def get_columns():
	return [
		{
			"fieldname": "project",
			"label": _("Project ID"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 130,
		},
		{"fieldname": "project_name", "label": _("Project Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "sold_to_party", "label": _("Sold to Party"), "fieldtype": "Data", "width": 180},
		{"fieldname": "challan_date", "label": _("Challan Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "challan_no",
			"label": _("Challan No"),
			"fieldtype": "Link",
			"options": "Delivery Note",
			"width": 160,
		},
		{
			"fieldname": "item_code",
			"label": _("Delilvery Note Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 140,
		},
		{"fieldname": "item_name", "label": _("Material Desc"), "fieldtype": "Data", "width": 200},
		{"fieldname": "plant", "label": _("Plant"), "fieldtype": "Data", "width": 130},
		{"fieldname": "source_wh", "label": _("Source (From)"), "fieldtype": "Data", "width": 140},
		{"fieldname": "destination", "label": _("Destination (To)"), "fieldtype": "Data", "width": 140},
		{"fieldname": "state", "label": _("State"), "fieldtype": "Data", "width": 100},
		{"fieldname": "ewaybill", "label": _("E-Way Bill No."), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "sales_order",
			"label": _("Sales Order No."),
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 150,
		},
		{
			"fieldname": "net_qty",
			"label": _("Delivery Note Item Qty"),
			"fieldtype": "Float",
			"width": 110,
			"precision": 3,
		},
		{
			"fieldname": "verified_qty",
			"label": _("Verified Qty"),
			"fieldtype": "Float",
			"width": 110,
			"precision": 3,
		},
		{
			"fieldname": "diff_qty",
			"label": _("Diff. Qty"),
			"fieldtype": "Float",
			"width": 100,
			"precision": 3,
		},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 80},
		{"fieldname": "hsn_code", "label": _("HSN Code"), "fieldtype": "Data", "width": 100},
		{"fieldname": "discount", "label": _("Discount %"), "fieldtype": "Percent", "width": 90},
		{
			"fieldname": "billing_doc",
			"label": _("Billing Doc. (SI)"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "rate",
			"label": _("Price Rs./MT"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 110,
		},
		{
			"fieldname": "bill_qty",
			"label": _("Bill Qty"),
			"fieldtype": "Float",
			"width": 90,
			"precision": 3,
		},
		{
			"fieldname": "net_value",
			"label": _("Net Value"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 110,
		},
		{
			"fieldname": "gst_value",
			"label": _("GST Value"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 110,
		},
		{
			"fieldname": "gross_value",
			"label": _("Gross Value"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 110,
		},
		{"fieldname": "lr_no", "label": _("Bill T./Cons. Note"), "fieldtype": "Data", "width": 130},
		{"fieldname": "vehicle_no", "label": _("Vehicle No."), "fieldtype": "Data", "width": 120},
		{"fieldname": "transport_name", "label": _("Transport Name"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "custom_transporter_invoice_date",
			"label": _("Transporter Invoice Date"),
			"fieldtype": "Date",
			"width": 130,
		},
		{
			"fieldname": "custom_transporter_invoice_number",
			"label": _("Transporter Invoice Number"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "custom_transporter_invoice_net_amount",
			"label": _("Transporter Invoice Net Amount"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 170,
		},
		{
			"fieldname": "transport_amount",
			"label": _("Gross Trans Amt"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 130,
		},
		{
			"fieldname": "custom_transporter_remarks",
			"label": _("Transporter Remarks"),
			"fieldtype": "Data",
			"width": 180,
		},
		{"fieldname": "po_no", "label": _("P.O. No."), "fieldtype": "Data", "width": 130},
		{"fieldname": "po_date", "label": _("P.O. Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "customer_address",
			"label": _("Customer Address"),
			"fieldtype": "Data",
			"width": 180,
		},
		{"fieldname": "ship_to_party", "label": _("Ship to Party"), "fieldtype": "Data", "width": 160},
	]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def get_data(filters):
	conds = _build_conditions(filters)
	sql = f"""
		SELECT
			dn.set_warehouse                                    AS plant,
			dn.posting_date                                     AS challan_date,
			dn.name                                             AS challan_no,
			IFNULL(dni.project, dn.project)                     AS project,
			IFNULL(proj.project_name, dn_proj.project_name)     AS project_name,
			cust.customer_name                                  AS sold_to_party,
			dn.shipping_address_name                            AS ship_to_party,
			CONCAT_WS(', ', addr.address_line1, addr.city)      AS customer_address,
			dni.item_code,
			dni.item_name,
			dn.set_warehouse                                    AS source_wh,
			IFNULL(dn.customer_address, addr.city)              AS destination,
			IFNULL(addr.state, '')                              AS state,
			dni.qty                                             AS net_qty,
			IFNULL(dni.custom_verified_qty, 0)                  AS verified_qty,
			(dni.qty - IFNULL(dni.custom_verified_qty, 0))      AS diff_qty,
			IFNULL(dn.po_no, '')                                AS po_no,
			dn.po_date,
			IFNULL(dni.against_sales_order, '')                 AS sales_order,
			IFNULL(sii.rate, 0)                                 AS rate,
			sii.amount                                          AS amount,
			dni.uom,
			IFNULL(sii.gst_hsn_code, IFNULL(i.gst_hsn_code, '')) AS hsn_code,
			IFNULL(sii.discount_percentage, 0)                  AS discount,
			IFNULL(sii.qty, 0)                                  AS bill_qty,
			si.name                                             AS billing_doc,
			IFNULL(si.net_total, 0)                             AS net_value,
			IFNULL(si.total_taxes_and_charges, 0)               AS gst_value,
			IFNULL(si.grand_total, 0)                           AS gross_value,
			IFNULL(dn.ewaybill, '')                             AS ewaybill,
			IFNULL(dn.lr_no, '')                                AS lr_no,
			IFNULL(dn.vehicle_no, '')                           AS vehicle_no,
			IFNULL(dn.transporter_name, '')                     AS transport_name,
			si.posting_date                                     AS posting_date,
			dn.custom_transporter_invoice_date                  AS custom_transporter_invoice_date,
			IFNULL(dn.custom_transporter_invoice_number, '')    AS custom_transporter_invoice_number,
			IFNULL(dn.custom_transporter_invoice_net_amount, 0) AS custom_transporter_invoice_net_amount,
			IFNULL(dn.custom_transporter_remarks, '')           AS custom_transporter_remarks,
			0                                                   AS transport_amount
		FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` dni    ON dni.parent  = dn.name
		LEFT  JOIN `tabCustomer`  cust            ON cust.name   = dn.customer
		LEFT  JOIN `tabAddress`   addr            ON addr.name   = dn.shipping_address_name
		LEFT  JOIN `tabSales Order` so            ON so.name     = dni.against_sales_order
		LEFT  JOIN `tabProject`   proj            ON proj.name   = dni.project
		LEFT  JOIN `tabProject`   dn_proj         ON dn_proj.name = dn.project
		LEFT  JOIN `tabSales Invoice Item` sii    ON sii.dn_detail = dni.name
		                                          AND sii.docstatus = 1
		LEFT  JOIN `tabSales Invoice` si          ON si.name     = sii.parent
		                                          AND si.docstatus = 1
		LEFT  JOIN `tabItem` i                    ON i.name      = dni.item_code
		WHERE  dn.docstatus = 1
		   AND dn.posting_date BETWEEN %(from_date)s AND %(to_date)s
		   AND dn.company     = %(company)s
		   {conds}
		ORDER BY dn.posting_date, dn.name, dni.idx
	"""
	return frappe.db.sql(sql, filters, as_dict=True)


def _as_list(value):
	"""MultiSelectList filters come in as a JSON array from the client."""
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value)
	return value if isinstance(value, list) else [value]


def _build_conditions(filters):
	c = []
	for key, column in (
		("warehouse", "dn.set_warehouse"),
		("customer", "dn.customer"),
		("item_code", "dni.item_code"),
		("transporter", "dn.transporter"),
	):
		values = _as_list(filters.get(key))
		if values:
			filters[key] = values
			c.append(f"AND {column} IN %({key})s")
		else:
			filters.pop(key, None)

	if filters.get("sales_order"):
		c.append("AND dni.against_sales_order = %(sales_order)s")
	if filters.get("vehicle_no"):
		filters["vehicle_no"] = f"%{filters['vehicle_no']}%"
		c.append("AND dn.vehicle_no LIKE %(vehicle_no)s")

	doc_type = filters.get("document_type")
	if doc_type in _DOCUMENT_TYPE_CONDITIONS:
		c.append(f"AND si.name IS NOT NULL AND {_DOCUMENT_TYPE_CONDITIONS[doc_type]}")

	inv = filters.get("invoice_status", "All")
	if inv == "Billed":
		c.append("AND si.name IS NOT NULL")
	elif inv == "Unbilled":
		c.append("AND si.name IS NULL")
	return " ".join(c)
