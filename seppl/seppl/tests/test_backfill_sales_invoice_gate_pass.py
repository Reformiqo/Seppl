"""Backfill patch: Sales Invoice Item → Gate Pass, matched on Manifest No.

The risk in this patch is a WRONG link, not a missing one:
`Gate Pass.sales_invoice` is what the "Get Items From → Gate Pass" picker
filters on, so a bad value silently hides a Gate Pass from billing
forever. These tests pin the decision table that keeps it conservative.
"""

import frappe
from frappe.tests import IntegrationTestCase

from seppl.patches.backfill_sales_invoice_gate_pass import (
	choose_gate_pass,
	schema_ready,
	unlinked_rows,
)

CUSTOMER = "COROMANDEL INTERNATIONAL LIMITED."


class TestBackfillSalesInvoiceGatePass(IntegrationTestCase):
	# ---- Decision table (pure, no DB) -----------------------------
	def test_single_candidate_for_the_same_customer_is_taken(self):
		self.assertEqual(
			choose_gate_pass([{"name": "GP-1", "customer": CUSTOMER}], CUSTOMER),
			("GP-1", "ok"),
		)

	def test_no_candidate_is_unmatched(self):
		self.assertEqual(choose_gate_pass([], CUSTOMER), (None, "unmatched"))

	def test_blank_customer_on_the_gate_pass_is_not_a_contradiction(self):
		"""Old Gate Passes predate the customer field being filled in;
		that is missing data, not a conflict."""
		self.assertEqual(
			choose_gate_pass([{"name": "GP-1", "customer": None}], CUSTOMER),
			("GP-1", "ok"),
		)

	def test_different_customer_is_refused(self):
		"""Linking an invoice to another customer's Gate Pass would be a
		billing error — leave it for a human."""
		self.assertEqual(
			choose_gate_pass([{"name": "GP-1", "customer": "SOMEONE ELSE"}], CUSTOMER),
			(None, "customer_mismatch"),
		)

	def test_two_candidates_are_narrowed_by_customer(self):
		self.assertEqual(
			choose_gate_pass(
				[
					{"name": "GP-1", "customer": CUSTOMER},
					{"name": "GP-2", "customer": "SOMEONE ELSE"},
				],
				CUSTOMER,
			),
			("GP-1", "ok"),
		)

	def test_two_candidates_for_the_same_customer_are_refused(self):
		self.assertEqual(
			choose_gate_pass(
				[
					{"name": "GP-1", "customer": CUSTOMER},
					{"name": "GP-2", "customer": CUSTOMER},
				],
				CUSTOMER,
			),
			(None, "ambiguous"),
		)

	# ---- Scan query -----------------------------------------------
	def test_scan_only_returns_rows_that_need_work(self):
		if not schema_ready():
			self.skipTest("Gate Pass / manifest fields not on this site")
		rows = unlinked_rows()
		if not rows:
			self.skipTest("Nothing left to backfill on this site")
		for row in rows[:50]:
			self.assertTrue(
				row.manifest_no,
				"Scan must not return rows without a Manifest No — there is nothing to match them on.",
			)
			invoice = frappe.db.get_value(
				"Sales Invoice", row.invoice, ["docstatus", "customer"], as_dict=True
			)
			self.assertLess(
				invoice.docstatus,
				2,
				"Cancelled invoices must be excluded, or a cancelled stub "
				"could claim a Gate Pass away from its live amendment.",
			)
			self.assertFalse(
				frappe.db.get_value("Sales Invoice Item", row.row_name, "custom_gate_pass"),
				"Scan must only pick up BLANK custom_gate_pass — the patch "
				"never overwrites an existing link.",
			)

	# ---- Preview is read-only -------------------------------------
	def test_preview_writes_nothing(self):
		if not schema_ready():
			self.skipTest("Gate Pass / manifest fields not on this site")
		from seppl.patches.backfill_sales_invoice_gate_pass import preview

		before = len(unlinked_rows())
		summary = preview()
		after = len(unlinked_rows())
		self.assertEqual(
			before,
			after,
			f"preview() must not write. {before} rows pending before, {after} after (summary: {summary}).",
		)
