"""Gate Pass `custom_service_items` — the service-charges table.

SEPPL raises service charges (transport, manpower, drum disposal fee ...)
on the same Gate Pass trip that carries the waste. They live in a second
table, `custom_service_items`, on its own child doctype — `Gate Pass
Service Item` — so a service charge can carry the fields it needs without
widening the waste grid, and so the doctype alone already tells the two
tables apart. What these tests pin:

  • **The table itself** — its child doctype and the Custom Field's module,
    which is what decides whether a fresh `bench migrate` still has it.
  • **Waste Inward date** is stamped by `seppl.overrides.waste_inward` when
    the Waste Inward is submitted — detox's equivalent loops `doc.items`
    on Gate Pass validate and never reaches this table, and by then the
    Gate Pass is submitted and won't be re-saved anyway.
  • **The Item picker** (non-stock Items only), the **Manifest No** copy
    and the **Create → Sales Invoice** button all live in
    `seppl/public/js/gate_pass_service_items.js`, shipped through the
    `doctype_js` hook. They were a Client Script row once, which is a row
    `bench migrate` never creates: the desk it was typed on billed the
    service charges and every other site silently billed the waste rows
    alone. These are contract tests over the shipped file — they pin the
    wiring, not the browser behaviour, which needs a UI walkthrough.
  • **Billing**, on both routes to an invoice, because neither maps the
    service table on its own. The Gate Pass form's Create button maps the
    SALES ORDER, so nothing typed on the Gate Pass reaches the invoice —
    `seppl.overrides.sales_order` appends the rows, and only when the
    caller names a Gate Pass. Sales Invoice → Get Items From → Gate Pass
    maps the GATE PASS, but through detox's mapper, which walks
    `Gate Pass Item` alone — `seppl.overrides.gate_pass_mapper` appends
    them inside the picker's loop, once per Gate Pass selected.

The billing tests drive the wire call the button actually makes —
`make_mapped_doc` with `args`, which is what puts the Gate Pass on
`frappe.flags.args` — against a Gate Pass walked through the real workflow
to Submitted, rather than asserting functions merely exist.
"""

import io
import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, now_datetime, nowdate

from seppl.overrides.gate_pass import (
	SERVICE_ITEM_DOCTYPE,
	SERVICE_ITEMS_FIELD,
	service_rows,
)
from seppl.overrides.gate_pass_mapper import GATE_PASS_TO_SALES_INVOICE
from seppl.overrides.waste_inward import stamp_inward_date_on_service_items

MANIFEST_NO = "MN-SVC-001"
# The client half ships as a file in the app, loaded on every site through
# the `doctype_js` hook. It used to be a Client Script row typed into the
# desk, which is a row a `bench migrate` never creates: the site it was
# typed on had the button that names the Gate Pass and every other site
# silently billed the waste rows alone.
CLIENT_JS = "public/js/gate_pass_service_items.js"
SO_TO_SALES_INVOICE = "erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice"


def client_script_body():
	"""The shipped client script's source, read from the app file.

	This is the file `doctype_js` hands the desk verbatim — Frappe reads it
	off disk into the form's `__js`, so the file IS what runs.
	"""
	return io.open(frappe.get_app_path("seppl", *CLIENT_JS.split("/")), encoding="utf-8").read()
# Building a Gate Pass from scratch on this site means clearing Customer's
# mandatory PAN / MSME fields and a Server Script that blocks direct Sales
# Order creation. Hanging the fixture off an Sales Order that already
# exists sidesteps both, and is closer to how a Gate Pass is really raised.
def live_sales_order():
	rows = frappe.db.sql(
		"""
		SELECT so.name, so.customer, so.project,
		       so.cost_center, soi.item_code, soi.rate, soi.uom, soi.warehouse
		FROM `tabSales Order` so
		JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE so.docstatus = 1
		  AND so.status NOT IN ('Closed', 'Cancelled')
		  AND so.company = %s
		ORDER BY so.creation DESC
		LIMIT 1
		""",
		("Saurashtra Enviro Projects Private Limited",),
		as_dict=True,
	)
	return rows[0] if rows else None


def service_item():
	"""A non-stock Item to bill the service charge against.

	Prefers one the site already has: Item, Customer and Supplier all carry
	Server Script mandatory rules here (PAN / MSME / ...), so a test that
	mints masters spends its time fighting those rather than testing the
	service table.
	"""
	existing = frappe.db.get_value(
		"Item", {"is_stock_item": 0, "disabled": 0, "has_variants": 0}, "name"
	)
	if existing:
		return existing
	name = "_Test Gate Pass Service Charge"
	if frappe.db.exists("Item", name):
		return name
	frappe.get_doc({
		"doctype": "Item",
		"item_code": name,
		"item_name": name,
		"item_group": frappe.get_all("Item Group", filters={"is_group": 0}, limit=1, pluck="name")[0],
		"stock_uom": "Nos",
		"is_stock_item": 0,
	}).insert(ignore_permissions=True)
	return name


def transporter():
	"""Any enabled Supplier — Gate Pass only needs the link to be valid."""
	return frappe.db.get_value("Supplier", {"disabled": 0}, "name")


class TestGatePassServiceItems(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		# Gate Pass auto-generated test records clash with the site's
		# Apr-Mar fiscal years; pre-seeding skips them, as in the detox
		# Gate Pass suite.
		if not hasattr(frappe.local, "test_objects"):
			frappe.local.test_objects = {}
		frappe.local.test_objects["Gate Pass"] = []
		super().setUpClass()

	def setUp(self):
		if not frappe.db.exists("DocType", "Gate Pass"):
			self.skipTest("Gate Pass doctype not installed on this site")
		if not frappe.get_meta("Gate Pass").has_field(SERVICE_ITEMS_FIELD):
			self.skipTest(
				f"Gate Pass.{SERVICE_ITEMS_FIELD} missing — did seppl's "
				"Custom Field fixture sync on migrate?"
			)

	# ---- 1. The field itself --------------------------------------
	def test_service_items_is_its_own_child_table(self):
		"""Its own child doctype, so a service row can carry the fields a
		service charge needs without widening the waste grid — and so the
		doctype alone already tells the two tables apart."""
		df = frappe.get_meta("Gate Pass").get_field(SERVICE_ITEMS_FIELD)
		self.assertEqual(df.fieldtype, "Table")
		self.assertEqual(df.options, SERVICE_ITEM_DOCTYPE)

	def test_service_items_field_is_owned_by_seppl(self):
		"""Module decides which app's fixture exports it. Anything but
		'Seppl' means `bench export-fixtures --app seppl` drops the field
		and a fresh migrate loses the table."""
		self.assertEqual(
			frappe.db.get_value("Custom Field", f"Gate Pass-{SERVICE_ITEMS_FIELD}", "module"),
			"Seppl",
		)

	def test_client_script_ships_with_the_app(self):
		"""Registered in `doctype_js`, so every site that installs seppl
		gets it. A Client Script row typed into one desk does not travel."""
		self.assertEqual(
			frappe.get_hooks("doctype_js", app_name="seppl").get("Gate Pass"),
			[CLIENT_JS],
		)
		self.assertTrue(client_script_body().strip(), f"{CLIENT_JS} is empty.")

	def test_item_picker_is_restricted_to_service_items(self):
		"""The query must be scoped to the parent fieldname. Set on the
		child field instead, it would narrow the WASTE grid's picker too —
		both grids are the same child doctype."""
		body = client_script_body()
		self.assertIn(f'set_query("item_code", SEPPL_SERVICE_TABLE', body)
		self.assertIn(f'SEPPL_SERVICE_TABLE = "{SERVICE_ITEMS_FIELD}"', body)
		self.assertIn("is_stock_item: 0", body, "Only non-stock (service) Items may be picked.")

	def test_manifest_no_is_copied_from_the_gate_pass_header(self):
		"""Both directions: typing the Manifest No must fill the rows that
		already exist, and a row added afterwards must not start blank."""
		body = client_script_body()
		self.assertIn("manifest_no: function (frm) {", body)
		self.assertIn(f"{SERVICE_ITEMS_FIELD}_add: function (frm, cdt, cdn) {{", body)
		self.assertEqual(
			body.count('"manifest_no", frm.doc.manifest_no'), 2,
			"Both the header handler and the row-add handler must stamp it.",
		)

	# ---- 2. Waste Inward date --------------------------------------
	def test_waste_inward_submit_stamps_the_date_on_service_rows(self):
		gp_name, _waste, _svc = self.submitted_gate_pass_with_services()
		inward_date = getdate(nowdate())

		stamp_inward_date_on_service_items(
			frappe._dict(gate_pass=gp_name, date=inward_date)
		)

		stamped = frappe.db.sql_list(
			f"""SELECT waste_inward_posting_date FROM `tab{SERVICE_ITEM_DOCTYPE}`
			    WHERE parent = %s AND parentfield = %s""",
			(gp_name, SERVICE_ITEMS_FIELD),
		)
		self.assertEqual(stamped, [inward_date])

	def test_waste_inward_stamp_leaves_the_waste_rows_to_detox(self):
		"""The waste rows detox's own hook owns must not be caught up in
		this write. Separate child doctypes make that structural now; the
		test stays because the two tables still hang off one parent."""
		gp_name, _waste, _svc = self.submitted_gate_pass_with_services()
		waste_rows = frappe.db.sql_list(
			"""SELECT name FROM `tabGate Pass Item`
			   WHERE parent = %s AND parentfield = 'items'""",
			(gp_name,),
		)
		self.assertTrue(waste_rows)
		service_rows_ = {row.name for row in service_rows(gp_name)}
		self.assertTrue(service_rows_)
		self.assertFalse(
			service_rows_ & set(waste_rows),
			"parentfield is what separates the two tables — filtering on "
			"parenttype instead would match both, or neither.",
		)

	def test_waste_inward_submit_hook_is_registered(self):
		self.assertIn(
			"seppl.overrides.waste_inward.on_submit",
			frappe.get_hooks("doc_events").get("Waste Inward", {}).get("on_submit", []),
		)

	# ---- 3. Billing via the Gate Pass form's Create button ---------
	# The override wraps the SALES ORDER mapper, so it sits in front of every
	# Sales Order → Sales Invoice on the site. These pin both halves: it acts
	# when a Gate Pass is named, and is inert otherwise.
	def test_so_mapper_override_is_registered(self):
		"""Without the override the Create button silently bills the Sales
		Order alone — the bug reported against GP-2026-00421."""
		self.assertEqual(
			frappe.override_whitelisted_method(SO_TO_SALES_INVOICE),
			"seppl.overrides.sales_order.make_sales_invoice",
		)

	def test_an_ordinary_sales_order_invoice_is_untouched(self):
		"""THE guard. Someone invoicing a Sales Order from the Sales Order
		form must get exactly what ERPNext builds — no Gate Pass rows, no
		recomputed totals, nothing."""
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")

		si = self.invoice_from_sales_order(sales_order)  # no gate_pass named

		self.assertNotIn(
			svc_item, [row.item_code for row in si.items],
			"A Sales Order invoice raised outside the Gate Pass must not pick "
			"up Gate Pass service charges.",
		)

	def test_create_button_bills_the_gate_pass_service_charges(self):
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")

		si = self.invoice_from_sales_order(sales_order, gate_pass=gp_name)

		svc_rows = [row for row in si.items if row.item_code == svc_item]
		self.assertEqual(
			len(svc_rows), 1,
			"The Sales Order mapper alone never sees the Gate Pass, so the "
			"service charge only appears if seppl appended it — exactly once.",
		)
		self.assertEqual(flt(svc_rows[0].qty), 2.0)
		self.assertEqual(flt(svc_rows[0].rate), 1500.0)
		self.assertEqual(flt(svc_rows[0].amount), 3000.0)

	def test_appended_row_carries_its_gate_pass(self):
		"""The back-link is what claims the Gate Pass on save — and that is
		what keeps the same charge off the NEXT invoice."""
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")
		si = self.invoice_from_sales_order(sales_order, gate_pass=gp_name)
		svc_row = next(row for row in si.items if row.item_code == svc_item)
		self.assertEqual(svc_row.get("custom_gate_pass"), gp_name)
		self.assertEqual(svc_row.get("custom_manifest_no"), MANIFEST_NO)

	def test_service_charge_lands_in_the_totals(self):
		"""Appending happens after the mapper already totalled the doc, so
		the totals have to be recomputed or the charge is invisible."""
		gp_name, _waste_item, _svc = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")
		si = self.invoice_from_sales_order(sales_order, gate_pass=gp_name)
		self.assertEqual(flt(si.net_total), sum(flt(row.amount) for row in si.items))

	def test_a_gate_pass_from_another_sales_order_is_refused(self):
		"""The name arrives from the browser, so it is re-checked against the
		DB — billing another Sales Order's charges here would be worse than
		billing none."""
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")
		frappe.db.set_value("Gate Pass", gp_name, "sales_order", None)
		self.addCleanup(
			frappe.db.set_value, "Gate Pass", gp_name, "sales_order", sales_order
		)

		si = self.invoice_from_sales_order(sales_order, gate_pass=gp_name)

		self.assertNotIn(svc_item, [row.item_code for row in si.items])

	def test_an_already_billed_gate_pass_is_not_billed_again(self):
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		sales_order = frappe.db.get_value("Gate Pass", gp_name, "sales_order")
		frappe.db.set_value("Gate Pass", gp_name, "sales_invoice", "SOME-EXISTING-SI")

		si = self.invoice_from_sales_order(sales_order, gate_pass=gp_name)

		self.assertNotIn(
			svc_item, [row.item_code for row in si.items],
			"A Gate Pass that already names a Sales Invoice must be skipped, "
			"or every later invoice for the Sales Order re-bills the charge.",
		)

	def test_create_button_names_the_gate_pass(self):
		"""The server guard is inert unless the button passes this, so the
		two halves have to stay in step."""
		body = client_script_body()
		self.assertIn("args: { gate_pass: frm.doc.name }", body)
		self.assertIn(
			'frm.remove_custom_button(__("Create Sales Invoice"), __("Create"))', body,
			"detox's button must be replaced, not duplicated alongside ours.",
		)

	# ---- 4. Billing via Sales Invoice → Get Items From → Gate Pass --
	# The other route to an invoice. It maps the GATE PASS (detox's mapper),
	# not the Sales Order — and that mapper walks `Gate Pass Item` alone, so
	# the service table is invisible to it. `seppl.overrides.gate_pass_mapper`
	# sits in the picker's map_docs loop and appends the rows there.
	def test_picker_bills_the_gate_pass_service_charges(self):
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()

		si = self.invoice_from_picker(gp_name)

		svc_rows = [row for row in si.items if row.item_code == svc_item]
		self.assertEqual(
			len(svc_rows), 1,
			"Get Items From → Gate Pass maps `Gate Pass Item` only, so the "
			"service charge appears exactly once — and only if seppl "
			"appended it.",
		)
		self.assertEqual(flt(svc_rows[0].qty), 2.0)
		self.assertEqual(flt(svc_rows[0].rate), 1500.0)
		self.assertEqual(flt(svc_rows[0].amount), 3000.0)

	def test_picker_service_row_carries_its_gate_pass(self):
		"""Same back-link the waste rows get: it is what claims the Gate
		Pass on save, and so what keeps the charge off the next invoice."""
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services()
		si = self.invoice_from_picker(gp_name)
		svc_row = next(row for row in si.items if row.item_code == svc_item)
		self.assertEqual(svc_row.get("custom_gate_pass"), gp_name)
		self.assertEqual(svc_row.get("custom_manifest_no"), MANIFEST_NO)

	def test_picker_service_charge_lands_in_the_totals(self):
		"""Appending happens after the mapper already totalled the doc, so
		the totals have to be recomputed or the charge is invisible."""
		gp_name, _waste_item, _svc = self.submitted_gate_pass_with_services()
		si = self.invoice_from_picker(gp_name)
		self.assertEqual(flt(si.net_total), sum(flt(row.amount) for row in si.items))

	def test_picker_confirm_qty_wins_over_gate_qty(self):
		"""Same rule the waste rows follow: the qty typed at the gate is
		what arrived, the confirmed qty is what finance bills."""
		gp_name, _waste_item, svc_item = self.submitted_gate_pass_with_services(
			confirm_qty=1.5
		)
		si = self.invoice_from_picker(gp_name)
		svc_row = next(row for row in si.items if row.item_code == svc_item)
		self.assertEqual(flt(svc_row.qty), 1.5)
		self.assertEqual(flt(svc_row.amount), 2250.0)

	def test_picker_bills_every_selected_gate_passs_own_charges(self):
		"""The picker aggregates many Gate Passes into one invoice. Each
		must contribute its own service rows, stamped with its own name —
		appending inside the loop is the only place that is still known."""
		first, _wi, svc_item = self.submitted_gate_pass_with_services()
		second, _wi2, _svc2 = self.submitted_gate_pass_with_services(
			manifest_no=MANIFEST_NO + "-B"
		)

		si = self.invoice_from_picker(first, second)

		stamped = sorted(
			row.get("custom_gate_pass")
			for row in si.items
			if row.item_code == svc_item and row.get("custom_gate_pass")
		)
		self.assertEqual(stamped, sorted([first, second]))
		# And the last Gate Pass's rows are totalled too — the recompute
		# runs after the loop, not inside it.
		self.assertEqual(flt(si.net_total), sum(flt(row.amount) for row in si.items))

	def test_picker_leaves_a_gate_pass_without_service_rows_alone(self):
		"""Most Gate Passes carry no service charge. Those invoices must
		come out byte-for-byte what detox's mapper built."""
		gp_name, waste_item, svc_item = self.submitted_gate_pass_with_services(
			with_services=False
		)
		si = self.invoice_from_picker(gp_name)
		self.assertNotIn(svc_item, [row.item_code for row in si.items])
		self.assertEqual([row.item_code for row in si.items], [waste_item])

	def invoice_from_picker(self, *gate_passes):
		"""Drive the wire call "Get Items From → Gate Pass" actually makes.

		The picker posts the whole selection to `frappe.model.mapper.map_docs`
		in one request, JSON-encoding every argument — which is the override
		seppl registers, and the loop the service rows are appended in.
		"""
		from seppl.overrides.gate_pass_mapper import map_docs

		return map_docs(
			GATE_PASS_TO_SALES_INVOICE, frappe.as_json(list(gate_passes)), None
		)

	def invoice_from_sales_order(self, sales_order, gate_pass=None):
		"""Drive the real wire call the Create button makes.

		`open_mapped_doc` posts to core `make_mapped_doc`, which resolves the
		override and puts `args` on `frappe.flags.args` — the exact route the
		guard reads. Calling the override directly would skip that.
		"""
		from frappe.model.mapper import make_mapped_doc

		frappe.flags.args = None
		self.addCleanup(setattr, frappe.flags, "args", None)
		return make_mapped_doc(
			SO_TO_SALES_INVOICE,
			sales_order,
			args=frappe.as_json({"gate_pass": gate_pass}) if gate_pass else None,
		)

	# ---- fixture ---------------------------------------------------
	def submitted_gate_pass_with_services(
		self, confirm_qty=0, with_services=True, manifest_no=MANIFEST_NO
	):
		"""A Gate Pass walked to Submitted through the real workflow.

		Reuses the detox Gate Pass suite's helpers so the document passes
		the same mandatory-field and workflow rules a user's would; only
		the service rows are ours.
		"""
		try:
			from detox_waste_management.detox_waste_management.doctype.gate_pass import (
				test_gate_pass as gp_fixtures,
			)
		except ImportError:
			self.skipTest("detox_waste_management Gate Pass test helpers unavailable")

		source = live_sales_order()
		if not source:
			self.skipTest("No open submitted Sales Order on this site to hang a Gate Pass off")

		svc_item = service_item()
		warehouse = source.warehouse or gp_fixtures.get_or_create_warehouse()
		gp = frappe.get_doc({
			"doctype": "Gate Pass",
			"transaction_type": "Inbound (Waste Receipt)",
			"company": gp_fixtures.COMPANY,
			"customer": source.customer,
			"sales_order": source.name,
			"project": source.project,
			"custom_cost_center": source.cost_center,
			"vehicle_no": "GJ-01-AB-1234",
			"driver_name": "Test Driver",
			"waste_type": "Hazardous",
			"waste_nature": "Solid",
			"waste_category": frappe.db.get_value("Waste Category", {"name": ["like", "%"]}, "name"),
			"term_card": "Yes",
			"packing_type": "HDPE Drums",
			"disposal_pathway": "Incineration",
			"target_warehouse": warehouse,
			"storage_location": warehouse,
			"transporter": transporter(),
			"lr_no": "LR-001",
			"lr_date": nowdate(),
			"vehicle_type": "Truck",
			"vehicle_entry_time": now_datetime(),
			"vehicle_exit_time": now_datetime(),
			"document_review_status": "Accepted",
			"date": nowdate(),
			# Unique per Gate Pass: a submitted Gate Pass already holding
			# this manifest number blocks the next one from saving.
			"manifest_no": manifest_no,
			# No `sales_order_item` on the row: this Gate Pass is not
			# consuming a Sales Order line, so the pending-qty and
			# rate-consistency checks (both keyed on that link) stay out
			# of the way of what is being tested here.
			"items": [{
				"item_code": source.item_code,
				"qty": 1,
				"rate": flt(source.rate),
				"uom": source.uom or "Nos",
			}],
		})
		if with_services:
			gp.append(SERVICE_ITEMS_FIELD, {
				"item_code": svc_item,
				"qty": 2,
				"rate": 1500,
				"uom": "Nos",
				"confirm_qty": confirm_qty,
				# What the shipped client script fills in on the form. Set
				# here because no browser runs in a test, and the invoice
				# reads it off the ROW, not off the header.
				"manifest_no": manifest_no,
			})
		gp.insert(ignore_permissions=True)
		self.addCleanup(self.discard_gate_pass, gp.name)

		self.walk_to_submitted(gp.name)
		return gp.name, source.item_code, svc_item

	def walk_to_submitted(self, gp_name):
		"""Draft → Vehicle Entered → QC Approved → Weighed → Exited → Submitted."""
		from detox_waste_management.detox_waste_management.doctype.gate_pass.test_gate_pass import (
			apply_workflow,
		)

		apply_workflow(gp_name, "Save Details")
		apply_workflow(gp_name, "Initiate QC")

		gp = frappe.get_doc("Gate Pass", gp_name)
		qi_name = gp.create_quality_inspection()
		qi = frappe.get_doc("Quality Inspection", qi_name)
		qi.status = "Accepted"
		# ABP2-I243 — QI won't submit without a recommended disposal pathway.
		qi.custom_disposal_pathway = "Incineration"
		qi.save(ignore_permissions=True)
		qi.submit()
		self.addCleanup(self.discard_quality_inspection, qi_name)

		frappe.db.set_value("Gate Pass", gp_name, "quality_review", "Accepted")
		apply_workflow(gp_name, "QC Accepted")

		gp = frappe.get_doc("Gate Pass", gp_name)
		gp.details_customer_gross_weight = 20.0
		gp.details_customer_tare_weight = 5.0
		gp.company_gross_weight = 21.0
		gp.company_tare_weight = 5.0
		gp.qc_required = 0
		gp.save(ignore_permissions=True)
		gp.reload()
		gp.mark_weighing_complete()
		gp.reload()
		gp.mark_vehicle_exit()
		apply_workflow(gp_name, "Submit")

	def discard_gate_pass(self, gp_name):
		if not frappe.db.exists("Gate Pass", gp_name):
			return
		gp = frappe.get_doc("Gate Pass", gp_name)
		gp.db_set("quality_inspection", "")
		if gp.docstatus == 1:
			gp.flags.ignore_permissions = True
			gp.cancel()
		frappe.delete_doc("Gate Pass", gp_name, force=True, ignore_permissions=True)

	def discard_quality_inspection(self, qi_name):
		if not frappe.db.exists("Quality Inspection", qi_name):
			return
		qi = frappe.get_doc("Quality Inspection", qi_name)
		qi.db_set("custom_gate_pass", "")
		if qi.docstatus == 1:
			qi.flags.ignore_permissions = True
			qi.cancel()
		frappe.delete_doc("Quality Inspection", qi_name, force=True, ignore_permissions=True)
