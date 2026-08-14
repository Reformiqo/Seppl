"""Sales Invoice ↔ Gate Pass: per-row Gate Pass + back-link.

Reported: "Sales Invoice → Get Items From → Gate Pass pulls the item
details, but the Sales Invoice Item rows don't say WHICH Gate Pass they
came from, and the Gate Pass's Sales Invoice field stays empty."

Two halves, both pinned here:

1. **Forward** — `seppl.overrides.gate_pass_mapper.map_docs` wraps the core
   mapper loop and stamps the source Gate Pass on every row it produced
   (`Sales Invoice Item.custom_gate_pass`), plus the header for the first
   source. The picker aggregates MANY Gate Passes into one invoice, so the
   header link alone can never describe a multi-Gate-Pass invoice.

2. **Back** — `seppl.overrides.sales_invoice.link_invoice_to_gate_pass`
   reads those row links back and stamps `Gate Pass.sales_invoice`. It runs
   on `on_update`, so a saved DRAFT already claims its Gate Passes; the
   picker filters on `sales_invoice in ("", null)`, so linking only at
   submit would let a second draft bill the same Gate Pass.
"""

import frappe
from frappe.tests import IntegrationTestCase

from seppl.overrides.gate_pass_mapper import (
	GATE_PASS_TO_SALES_INVOICE,
	stamp_source_gate_pass,
)
from seppl.overrides.sales_invoice import (
	gate_passes_on_invoice,
	link_invoice_to_gate_pass,
)


def billable_gate_pass(customer=None, exclude=None):
	"""A submitted Inbound Gate Pass with items and no invoice yet."""
	return frappe.db.sql(
		"""
		SELECT gp.name
		FROM `tabGate Pass` gp
		JOIN `tabGate Pass Item` gpi ON gpi.parent = gp.name
		WHERE gp.docstatus = 1
		  AND gp.transaction_type = 'Inbound (Waste Receipt)'
		  AND (gp.sales_invoice IS NULL OR gp.sales_invoice = '')
		  AND gp.customer IS NOT NULL AND gp.customer != ''
		  AND (%(customer)s IS NULL OR gp.customer = %(customer)s)
		  AND (%(exclude)s IS NULL OR gp.name != %(exclude)s)
		GROUP BY gp.name
		ORDER BY gp.modified DESC
		LIMIT 1
		""",
		{"customer": customer, "exclude": exclude},
		pluck=True,
	)


class TestSalesInvoiceGatePassLink(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("DocType", "Gate Pass"):
			self.skipTest("Gate Pass doctype not installed on this site")

	# ---- 1. Custom Field contract ---------------------------------
	def test_sales_invoice_item_has_custom_gate_pass(self):
		cf = frappe.db.get_value(
			"Custom Field",
			{"dt": "Sales Invoice Item", "fieldname": "custom_gate_pass"},
			["fieldtype", "options", "read_only", "in_list_view"],
			as_dict=True,
		)
		self.assertIsNotNone(
			cf,
			"Custom Field 'custom_gate_pass' missing on Sales Invoice Item. "
			"Did seppl/fixtures/custom_field.json sync on migrate?",
		)
		self.assertEqual(cf.fieldtype, "Link")
		self.assertEqual(
			cf.options,
			"Gate Pass",
			"Must be a Link to Gate Pass so the row is clickable through to the source document.",
		)
		self.assertEqual(
			cf.read_only,
			1,
			"Mapper-populated — hand-editing it would desync the Gate Pass.sales_invoice back-link.",
		)
		self.assertEqual(
			cf.in_list_view,
			1,
			"Must be in_list_view so the Gate Pass number shows in the items grid without per-row config.",
		)

	# ---- 2. The stamp ---------------------------------------------
	def test_stamp_fills_header_and_every_row(self):
		doc = frappe._dict(
			{
				"items": [
					frappe._dict({"item_code": "A"}),
					frappe._dict({"item_code": "B"}),
				]
			}
		)
		stamp_source_gate_pass(doc, "GP-1")
		self.assertEqual(doc.custom_gate_pass, "GP-1")
		self.assertEqual([r.custom_gate_pass for r in doc["items"]], ["GP-1", "GP-1"])

	def test_stamp_never_overwrites_an_earlier_gate_pass(self):
		"""The whole point of running inside the map_docs loop: rows added
		by an earlier source keep THEIR Gate Pass, and only the new rows
		pick up the current one."""
		doc = frappe._dict(
			{
				"custom_gate_pass": "GP-1",
				"items": [
					frappe._dict({"item_code": "A", "custom_gate_pass": "GP-1"}),
					frappe._dict({"item_code": "B"}),
				],
			}
		)
		stamp_source_gate_pass(doc, "GP-2")
		self.assertEqual(doc.custom_gate_pass, "GP-1", "Header keeps the FIRST source Gate Pass.")
		self.assertEqual([r.custom_gate_pass for r in doc["items"]], ["GP-1", "GP-2"])

	# ---- 3. Mapper wrapper drives the real mapper -----------------
	def test_map_docs_stamps_a_real_gate_pass(self):
		gate_pass = billable_gate_pass()
		if not gate_pass:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		from seppl.overrides.gate_pass_mapper import map_docs

		si = map_docs(GATE_PASS_TO_SALES_INVOICE, frappe.as_json([gate_pass[0]]), None)
		self.assertGreater(
			len(si.items or []),
			0,
			"Mapper produced an invoice with no items — nothing to stamp.",
		)
		self.assertEqual(si.custom_gate_pass, gate_pass[0])
		for row in si.items:
			self.assertEqual(
				row.custom_gate_pass,
				gate_pass[0],
				f"Every row must carry its source Gate Pass {gate_pass[0]!r}; "
				f"got {row.custom_gate_pass!r} on item {row.item_code!r}.",
			)

	def test_map_docs_keeps_each_source_on_its_own_rows(self):
		first = billable_gate_pass()
		if not first:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		first = first[0]
		customer = frappe.db.get_value("Gate Pass", first, "customer")
		second = billable_gate_pass(customer=customer, exclude=first)
		if not second:
			self.skipTest(
				f"Only one unbilled Inbound Gate Pass for {customer} — "
				"can't exercise multi-Gate-Pass aggregation"
			)
		from seppl.overrides.gate_pass_mapper import map_docs

		si = map_docs(GATE_PASS_TO_SALES_INVOICE, frappe.as_json([first, second[0]]), None)
		self.assertEqual(
			{row.custom_gate_pass for row in si.items},
			{first, second[0]},
			"Rows from a two-Gate-Pass pull must carry both source Gate Passes.",
		)
		self.assertEqual(si.custom_gate_pass, first)

	def test_map_docs_delegates_other_mappings_to_core(self):
		"""This override sits on a core method used by every 'get items
		from' picker on the site — anything that isn't the Gate Pass mapper
		must reach core untouched."""
		import inspect

		from seppl.overrides import gate_pass_mapper

		src = inspect.getsource(gate_pass_mapper.map_docs)
		self.assertIn(
			"return _core_map_docs(method, source_names, target_doc, args)",
			src,
			"Non-Gate-Pass mappings must be delegated to core map_docs "
			"verbatim, or every other picker on the site changes behaviour.",
		)

	# ---- 4. Collector ---------------------------------------------
	def test_gate_passes_on_invoice_merges_header_and_rows(self):
		doc = frappe._dict(
			{
				"custom_gate_pass": "GP-A",
				"items": [
					frappe._dict({"custom_gate_pass": "GP-A"}),
					frappe._dict({"custom_gate_pass": "GP-B"}),
					frappe._dict({"custom_gate_pass": None}),
					frappe._dict({"custom_gate_pass": "GP-B"}),
				],
			}
		)
		self.assertEqual(
			gate_passes_on_invoice(doc),
			["GP-A", "GP-B"],
			"Must dedupe, drop blanks and keep first-seen order.",
		)

	def test_gate_passes_on_invoice_handles_a_manual_invoice(self):
		"""An ordinary invoice with no Gate Pass anywhere yields nothing —
		the hook must be a no-op on the rest of the site's invoicing."""
		doc = frappe._dict({"items": [frappe._dict({"item_code": "X"})]})
		self.assertEqual(gate_passes_on_invoice(doc), [])

	# ---- 5. Back-link ---------------------------------------------
	def test_draft_save_links_gate_pass_back_to_invoice(self):
		gate_pass = billable_gate_pass()
		if not gate_pass:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		from seppl.overrides.gate_pass_mapper import map_docs

		si = map_docs(GATE_PASS_TO_SALES_INVOICE, frappe.as_json([gate_pass[0]]), None)
		si.flags.ignore_permissions = True
		si.insert(ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value("Gate Pass", gate_pass[0], "sales_invoice"),
			si.name,
			"Saving the DRAFT must already claim the Gate Pass — the picker "
			"filters on sales_invoice being empty, so linking only at submit "
			"lets a second draft bill the same Gate Pass.",
		)

	def test_dropping_the_row_releases_the_gate_pass(self):
		gate_pass = billable_gate_pass()
		if not gate_pass:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		from seppl.overrides.gate_pass_mapper import map_docs

		si = map_docs(GATE_PASS_TO_SALES_INVOICE, frappe.as_json([gate_pass[0]]), None)
		si.flags.ignore_permissions = True
		si.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Gate Pass", gate_pass[0], "sales_invoice"), si.name)

		# User clears the Gate Pass rows and saves again.
		si.custom_gate_pass = None
		for row in si.items:
			row.custom_gate_pass = None
		link_invoice_to_gate_pass(si)

		self.assertFalse(
			frappe.db.get_value("Gate Pass", gate_pass[0], "sales_invoice"),
			"A Gate Pass must be released once no row on the invoice "
			"references it, or it stays invisible to the picker forever.",
		)

	def test_gate_pass_claimed_by_a_live_invoice_is_left_alone(self):
		gate_pass = billable_gate_pass()
		if not gate_pass:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		live_si = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
		if not live_si:
			self.skipTest("No submitted Sales Invoice on this site")
		frappe.db.set_value("Gate Pass", gate_pass[0], "sales_invoice", live_si)

		doc = frappe._dict(
			{
				"name": "SINV-MINE",
				"amended_from": None,
				"custom_gate_pass": gate_pass[0],
				"items": [frappe._dict({"custom_gate_pass": gate_pass[0]})],
			}
		)
		link_invoice_to_gate_pass(doc)  # must not raise

		self.assertEqual(
			frappe.db.get_value("Gate Pass", gate_pass[0], "sales_invoice"),
			live_si,
			"Must not steal a Gate Pass already billed on a live invoice.",
		)

	def test_gate_pass_held_by_a_cancelled_invoice_is_reclaimed(self):
		"""Finance cancels an invoice and re-bills the Gate Pass on a new
		one. A cancelled stub must not hold the Gate Pass hostage."""
		gate_pass = billable_gate_pass()
		if not gate_pass:
			self.skipTest("No unbilled submitted Inbound Gate Pass with items")
		dead_si = frappe.db.get_value("Sales Invoice", {"docstatus": 2}, "name")
		if not dead_si:
			self.skipTest("No cancelled Sales Invoice on this site")
		frappe.db.set_value("Gate Pass", gate_pass[0], "sales_invoice", dead_si)

		doc = frappe._dict(
			{
				"name": "SINV-MINE",
				"amended_from": None,
				"custom_gate_pass": gate_pass[0],
				"items": [frappe._dict({"custom_gate_pass": gate_pass[0]})],
			}
		)
		link_invoice_to_gate_pass(doc)

		self.assertEqual(
			frappe.db.get_value("Gate Pass", gate_pass[0], "sales_invoice"),
			"SINV-MINE",
			"A Gate Pass whose invoice was cancelled must be re-billable.",
		)

	# ---- 6. Hook wiring -------------------------------------------
	def test_hooks_are_wired(self):
		from seppl import hooks

		self.assertEqual(
			hooks.doc_events["Sales Invoice"]["on_update"],
			"seppl.overrides.sales_invoice.on_update",
			"The back-link must run on on_update so a saved draft claims its "
			"Gate Passes, not only on submit.",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.model.mapper.map_docs"],
			"seppl.overrides.gate_pass_mapper.map_docs",
		)
