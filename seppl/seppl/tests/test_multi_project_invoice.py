"""ABP2-I406 — one Sales Invoice covering several Sub Projects.

The BRD asks for line-level Project and Cost Centre with the GL split to
match. Most of that is already ERPNext: `Sales Invoice Item` carries its own
`project` and a mandatory `cost_center`, and the income GL entry is written
per line against `item.cost_center` / `item.project`. Those facts are pinned
below, because the whole design rests on them — if a future ERPNext release
posts revenue at header level again, this feature is silently wrong.

What is actually new is the two-level hierarchy of §4 — Group Project on the
header, Sub Project on the line — and the rule that one invoice may only
carry Sub Projects of a single Group Project.

Backward compatibility is a requirement in its own right (NFR): an invoice
that names no Group Project and no Sub Project must pass through untouched,
and most tests here exist to prove the new rules stay asleep until the
feature is used.
"""

import frappe
from frappe.tests import IntegrationTestCase

from seppl.overrides.project import (
    group_project_of,
    is_group_project,
    validate_hierarchy,
)
from seppl.overrides.sales_invoice import validate_multi_project_mapping


def row(idx, project=None, cost_center="CC - X", group=None):
    return frappe._dict(
        idx=idx,
        doctype="Sales Invoice Item",
        project=project,
        cost_center=cost_center,
        custom_group_project=group,
    )


def invoice(group_project=None, rows=None, project=None):
    return frappe._dict(
        doctype="Sales Invoice",
        name="TEST-SI-I406",
        project=project,
        custom_group_project=group_project,
        items=rows or [],
    )


class TestABP2I406Fields(IntegrationTestCase):
    """The custom fields the feature is built on."""

    def test_01_project_carries_the_hierarchy(self):
        meta = frappe.get_meta("Project")
        self.assertTrue(meta.has_field("custom_is_group_project"))
        self.assertTrue(meta.has_field("custom_group_project"))
        self.assertEqual(meta.get_field("custom_group_project").options, "Project")

    def test_02_group_project_is_on_the_invoice_header(self):
        field = frappe.get_meta("Sales Invoice").get_field("custom_group_project")
        self.assertIsNotNone(field, "FR-01 needs a Group Project on the header")
        self.assertEqual(field.options, "Project")

    def test_03_the_line_group_project_is_read_only(self):
        """FR-03 — inherited from the header, never typed."""
        field = frappe.get_meta("Sales Invoice Item").get_field("custom_group_project")
        self.assertIsNotNone(field)
        self.assertTrue(field.read_only, "the user must not set it per line")

    def test_04_the_line_already_carries_project_and_cost_centre(self):
        """FR-02 / FR-04 need no new fields — ERPNext has both, and Cost
        Centre is already mandatory, which is FR-07 (c) for free."""
        meta = frappe.get_meta("Sales Invoice Item")
        self.assertTrue(meta.has_field("project"))
        self.assertTrue(meta.get_field("cost_center").reqd, "FR-07 (c) relies on this")


class TestABP2I406GLSplit(IntegrationTestCase):
    def test_05_revenue_posts_per_line_not_per_header(self):
        """FR-06. The reason no accounting code was written: ERPNext already
        writes the income credit against the line's own cost centre and
        project."""
        import inspect

        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

        source = inspect.getsource(SalesInvoice.make_item_gl_entries)
        self.assertIn('"cost_center": item.cost_center', source)
        self.assertIn('"project": item.project', source)

    def test_05a_tax_does_not_follow_the_line_yet(self):
        """FR-08 is NOT delivered, and this records why rather than leaving
        it to be discovered at an audit.

        Tax is posted once per Sales Taxes and Charges row, against that
        row's cost centre and with no project at all — there is no per-line
        attribution to apportion. Splitting it would mean rewriting the tax
        GL, and the BRD's own §5.3 flags place-of-supply and CGST/SGST/IGST
        risk that needs a tax opinion first.

        If a future ERPNext release starts tagging tax by project, this test
        fails and FR-08 can be revisited."""
        import inspect

        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

        source = inspect.getsource(SalesInvoice.make_tax_gl_entries)
        self.assertIn('"cost_center": tax.cost_center', source)
        self.assertNotIn('"project"', source)


class TestABP2I406Hierarchy(IntegrationTestCase):
    """§4 — Group Project above, Sub Project below, and nothing else."""

    def test_06_a_group_project_cannot_have_a_parent(self):
        doc = frappe._dict(
            doctype="Project",
            name="GRP-001",
            custom_is_group_project=1,
            custom_group_project="GRP-002",
            get_doc_before_save=lambda: None,
        )
        with self.assertRaises(frappe.ValidationError):
            validate_hierarchy(doc)

    def test_07_a_project_cannot_be_its_own_group(self):
        doc = frappe._dict(
            doctype="Project",
            name="PROJ-0001",
            custom_is_group_project=0,
            custom_group_project="PROJ-0001",
            get_doc_before_save=lambda: None,
        )
        with self.assertRaises(frappe.ValidationError):
            validate_hierarchy(doc)

    def test_08_the_parent_must_be_flagged_as_a_group(self):
        plain = frappe.db.get_value(
            "Project", {"custom_is_group_project": ("!=", 1)}, "name"
        )
        if not plain:
            self.skipTest("no ordinary Project on this site")

        doc = frappe._dict(
            doctype="Project",
            name="__TEST_SUB__",
            custom_is_group_project=0,
            custom_group_project=plain,
            get_doc_before_save=lambda: None,
        )
        with self.assertRaises(frappe.ValidationError):
            validate_hierarchy(doc)

    def test_09_an_ordinary_project_is_left_alone(self):
        """Every project on this site today has neither flag set. None of
        them may start failing to save."""
        doc = frappe._dict(
            doctype="Project",
            name="PROJ-0001",
            custom_is_group_project=0,
            custom_group_project=None,
            get_doc_before_save=lambda: None,
        )
        validate_hierarchy(doc)  # must not raise

    def test_10_lookups_read_the_hierarchy(self):
        self.assertFalse(is_group_project(None))
        self.assertFalse(is_group_project("__NO_SUCH_PROJECT__"))
        self.assertIsNone(group_project_of(None))
        self.assertIsNone(group_project_of("__NO_SUCH_PROJECT__"))


class TestABP2I406InvoiceRules(IntegrationTestCase):
    # ------------------------------------------------------------------
    # backward compatibility — the rules stay asleep
    # ------------------------------------------------------------------
    def test_11_a_single_project_invoice_is_untouched(self):
        """NFR — Backward Compatibility. No Group Project, no Sub Project:
        nothing here may fire, including the blank-Sub-Project check."""
        doc = invoice(rows=[row(1, project=None, cost_center=None)])
        validate_multi_project_mapping(doc)  # must not raise
        self.assertIsNone(doc.items[0].custom_group_project)

    def test_12_a_plain_project_on_a_line_is_not_a_sub_project(self):
        """A line naming an ordinary project — the way invoices are raised
        today — must not drag the invoice into the new rules."""
        plain = frappe.db.get_value(
            "Project",
            {"custom_group_project": ("in", ["", None])},
            "name",
        )
        if not plain:
            self.skipTest("no ordinary Project on this site")

        doc = invoice(rows=[row(1, project=plain)])
        validate_multi_project_mapping(doc)  # must not raise

    # ------------------------------------------------------------------
    # the rules, once the feature is used
    # ------------------------------------------------------------------
    def _hierarchy(self):
        """A Group Project with at least two Sub Projects, if the site has
        one configured."""
        groups = frappe.get_all(
            "Project", filters={"custom_is_group_project": 1}, pluck="name"
        )
        for group in groups:
            subs = frappe.get_all(
                "Project", filters={"custom_group_project": group}, pluck="name"
            )
            if len(subs) >= 2:
                return group, subs
        return None, []

    def test_13_lines_from_one_group_are_accepted_and_stamped(self):
        """§3.2 — the point of the whole ticket: two Sub Projects, one
        invoice. And FR-03: each line comes out carrying the Group."""
        group, subs = self._hierarchy()
        if not group:
            self.skipTest("no Group Project with two Sub Projects configured yet")

        doc = invoice(group, [row(1, subs[0]), row(2, subs[1])])
        validate_multi_project_mapping(doc)

        for line in doc.items:
            self.assertEqual(line.custom_group_project, group)

    def test_14_sub_projects_from_two_groups_cannot_share_an_invoice(self):
        """§3.3 — the constraint the BRD calls out explicitly."""
        pairs = frappe.db.sql(
            """
            SELECT custom_group_project AS grp, name
            FROM `tabProject`
            WHERE COALESCE(custom_group_project, '') != ''
            ORDER BY custom_group_project
            """,
            as_dict=True,
        )
        by_group = {}
        for pair in pairs:
            by_group.setdefault(pair.grp, []).append(pair.name)
        if len(by_group) < 2:
            self.skipTest("need Sub Projects under two different Group Projects")

        (group_a, subs_a), (group_b, subs_b) = list(by_group.items())[:2]
        doc = invoice(group_a, [row(1, subs_a[0]), row(2, subs_b[0])])
        with self.assertRaises(frappe.ValidationError) as caught:
            validate_multi_project_mapping(doc)
        self.assertIn(group_b, str(caught.exception))

    def test_15_a_sub_project_on_a_line_demands_its_group_on_the_header(self):
        """FR-01, from the other direction — the header cannot be left blank
        once a line names a Sub Project."""
        sub = frappe.db.get_value(
            "Project", {"custom_group_project": ("not in", ["", None])}, "name"
        )
        if not sub:
            self.skipTest("no Sub Project configured yet")

        doc = invoice(None, [row(1, sub)])
        with self.assertRaises(frappe.ValidationError):
            validate_multi_project_mapping(doc)

    def test_16_the_header_group_project_must_really_be_one(self):
        plain = frappe.db.get_value(
            "Project", {"custom_is_group_project": ("!=", 1)}, "name"
        )
        if not plain:
            self.skipTest("no ordinary Project on this site")

        doc = invoice(plain, [row(1, plain)])
        with self.assertRaises(frappe.ValidationError):
            validate_multi_project_mapping(doc)

    def test_17_a_blank_sub_project_blocks_the_invoice(self):
        """FR-07 (b)."""
        group, subs = self._hierarchy()
        if not group:
            self.skipTest("no Group Project with two Sub Projects configured yet")

        doc = invoice(group, [row(1, subs[0]), row(2, project=None)])
        with self.assertRaises(frappe.ValidationError) as caught:
            validate_multi_project_mapping(doc)
        self.assertIn("Sub Project", str(caught.exception))

    def test_18_a_blank_cost_centre_blocks_the_invoice(self):
        """FR-07 (c). ERPNext makes the field mandatory anyway; this is the
        message that names the row and the reason."""
        group, subs = self._hierarchy()
        if not group:
            self.skipTest("no Group Project with two Sub Projects configured yet")

        doc = invoice(group, [row(1, subs[0], cost_center=None)])
        with self.assertRaises(frappe.ValidationError) as caught:
            validate_multi_project_mapping(doc)
        self.assertIn("Cost Centre", str(caught.exception))

    def test_19_the_header_project_belongs_to_the_single_project_mode(self):
        """Both set is a contradiction, and a quiet one: the header Project
        feeds any line without its own, and ABP2-I273 filters the line Cost
        Centre lookup by it."""
        group, subs = self._hierarchy()
        if not group:
            self.skipTest("no Group Project with two Sub Projects configured yet")

        doc = invoice(group, [row(1, subs[0])], project=subs[0])
        with self.assertRaises(frappe.ValidationError):
            validate_multi_project_mapping(doc)


class TestABP2I406Wiring(IntegrationTestCase):
    def test_20_hooks_are_wired(self):
        events = frappe.get_hooks("doc_events") or {}

        def chain(doctype, event):
            handlers = (events.get(doctype) or {}).get(event) or []
            return [handlers] if isinstance(handlers, str) else list(handlers)

        self.assertIn("seppl.overrides.project.validate", chain("Project", "validate"))
        self.assertIn(
            "seppl.overrides.sales_invoice.validate_multi_project_mapping",
            chain("Sales Invoice", "validate"),
        )

    def test_21_the_form_script_is_loaded(self):
        scripts = frappe.get_hooks("doctype_js") or {}
        loaded = scripts.get("Sales Invoice") or []
        if isinstance(loaded, str):
            loaded = [loaded]
        self.assertTrue(
            any("sales_invoice_multi_project" in path for path in loaded),
            "the filtered Sub Project lookup (FR-05) comes from this file",
        )


class TestABP2I406FormBehaviour(IntegrationTestCase):
    """The form script. Asserted against its source — none of it is a
    validation, so there is nothing to call server-side."""

    @staticmethod
    def script():
        import pathlib

        return (
            pathlib.Path(frappe.get_app_path("seppl"))
            / "public"
            / "js"
            / "sales_invoice_multi_project.js"
        ).read_text()

    def test_22_choosing_a_group_clears_lines_that_do_not_belong_to_it(self):
        """A line pulled from a Sales Order or Gate Pass arrives carrying that
        document's project, which belongs to no Group Project at all. Leaving
        it there is what produced 'PROJ-0024 is not a Sub Project' at save
        time — the user had no way to know which rows to fix."""
        js = self.script()
        self.assertIn("if (owner[row.project] === group) return;", js)
        self.assertIn('frappe.model.set_value(row.doctype, row.name, "cost_center", "")', js)

    def test_23_clearing_a_header_dimension_clears_the_column(self):
        """Emptying Project or Cost Center on the header is how the user says
        'these are per-line now'."""
        js = self.script()
        self.assertIn("seppl_mp_clear_rows_with_header(frm, \"project\")", js)
        self.assertIn("seppl_mp_clear_rows_with_header(frm, \"cost_center\")", js)

    def test_24_only_a_value_that_was_set_and_is_now_empty_clears_rows(self):
        """Without this guard a programmatic reset of an already-empty field
        would wipe the lines mid-mapping."""
        js = self.script()
        self.assertIn("if (frm.doc[fieldname] || !previous) return;", js)

    def test_25_the_script_stays_es5(self):
        """Matches the rest of this app's form scripts."""
        code = "\n".join(
            line for line in self.script().splitlines() if not line.strip().startswith("//")
        )
        for token in (" => ", "const ", "let ", "`"):
            self.assertNotIn(token, code)


class TestABP2I406ProjectForm(IntegrationTestCase):
    """The Project master's own lookup. The server already refuses a parent
    that is not a Group Project; this keeps the user from picking one."""

    @staticmethod
    def script():
        import pathlib

        return (
            pathlib.Path(frappe.get_app_path("seppl"))
            / "public"
            / "js"
            / "project_group_hierarchy.js"
        ).read_text()

    def test_26_the_lookup_offers_group_projects_only(self):
        js = self.script()
        self.assertIn('frm.set_query("custom_group_project"', js)
        self.assertIn("custom_is_group_project: 1", js)

    def test_27_the_lookup_carries_no_other_filter(self):
        """A self-exclusion filter was tried and removed. It is unreachable —
        a Group Project has this field hidden, and a non-group can never
        appear in a list filtered to groups — and Frappe prints every filter
        under the lookup, so on an unsaved Project it put the temporary
        document name in front of the user."""
        js = self.script()
        self.assertNotIn("frm.doc.name", js)
        self.assertIn("return { filters: { custom_is_group_project: 1 } };", js)

    def test_28_ticking_is_group_project_empties_the_parent(self):
        """depends_on hides the field but leaves the value, which would trip
        the server's "a Group Project cannot have a parent" guard from a
        field the user can no longer see."""
        js = self.script()
        self.assertIn('frm.set_value("custom_group_project", "")', js)

    def test_29_the_script_is_loaded(self):
        scripts = frappe.get_hooks("doctype_js") or {}
        loaded = scripts.get("Project") or []
        if isinstance(loaded, str):
            loaded = [loaded]
        self.assertTrue(any("project_group_hierarchy" in path for path in loaded))

    def test_30_the_script_stays_es5(self):
        code = "\n".join(
            line for line in self.script().splitlines() if not line.strip().startswith("//")
        )
        for token in (" => ", "const ", "let ", "`"):
            self.assertNotIn(token, code)
