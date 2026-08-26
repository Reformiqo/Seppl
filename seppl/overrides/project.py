"""ABP2-I406 §4 — the Group Project / Sub Project hierarchy.

Two levels, and only two:

  Level 1  Group Project   a business initiative or client engagement.
                           Selected on the invoice header only.
  Level 2  Sub Project     the working project. All billing and every GL
                           entry lands here.

Held on the Project master itself rather than in a new doctype, so every
report, filter and link field that already points at Project keeps working:

  * `custom_is_group_project` marks a project as Level 1;
  * `custom_group_project` names the Level 1 parent of a Level 2 project.

A project with neither is an ordinary project, exactly as before. That is
what keeps the existing single-project invoices working (NFR — Backward
Compatibility): the hierarchy only exists for projects that opt into it.
"""

import frappe
from frappe import _


def validate(doc, method=None):
    validate_hierarchy(doc)


# ----------------------------------------------------------------------
# lookups — used by the Sales Invoice validation too
# ----------------------------------------------------------------------
def is_group_project(project: str | None) -> bool:
    if not project:
        return False
    return bool(frappe.db.get_value("Project", project, "custom_is_group_project"))


def group_project_of(project: str | None) -> str | None:
    """The Group Project a Sub Project belongs to, or None for an ordinary
    project that is not part of the hierarchy."""
    if not project:
        return None
    return frappe.db.get_value("Project", project, "custom_group_project") or None


def sub_projects_of(group_project: str) -> list[str]:
    return frappe.get_all(
        "Project", filters={"custom_group_project": group_project}, pluck="name"
    )


def has_billing_history(project: str) -> bool:
    """Whether anything has been invoiced against this project.

    Raw SQL because `Sales Invoice Item` is a child table, and this bench's
    DatabaseQuery cannot be pointed at one without `parent_doctype` (the
    trap that broke ABP2-I713 in production).
    """
    if not project:
        return False
    rows = frappe.db.sql(
        """
        SELECT 1 FROM `tabSales Invoice Item`
        WHERE project = %s AND docstatus = 1
        LIMIT 1
        """,
        (project,),
    )
    return bool(rows)


# ----------------------------------------------------------------------
# the rules — BRD §4.1 "Key Rule" and §4.5
# ----------------------------------------------------------------------
def validate_hierarchy(doc):
    _a_group_project_has_no_parent(doc)
    _a_parent_must_be_a_group_project(doc)
    _no_self_reference(doc)
    _keep_the_parent_once_billing_exists(doc)
    _keep_the_group_flag_while_sub_projects_exist(doc)


def _a_group_project_has_no_parent(doc):
    """Two levels, not three."""
    if doc.get("custom_is_group_project") and doc.get("custom_group_project"):
        frappe.throw(
            _(
                "{0} is marked as a Group Project, so it sits at the top of the "
                "hierarchy and cannot itself belong to another Group Project. "
                "Clear the Group Project field, or untick Is Group Project."
            ).format(doc.name or doc.get("project_name")),
            title=_("Group Project cannot have a parent"),
        )


def _a_parent_must_be_a_group_project(doc):
    parent = doc.get("custom_group_project")
    if not parent or parent == doc.name:
        return
    if not is_group_project(parent):
        frappe.throw(
            _(
                "{0} is not a Group Project, so it cannot be the parent of {1}. "
                "Open {0} and tick Is Group Project first."
            ).format(parent, doc.name or doc.get("project_name")),
            title=_("Not a Group Project"),
        )


def _no_self_reference(doc):
    if doc.get("custom_group_project") and doc.get("custom_group_project") == doc.name:
        frappe.throw(
            _("A project cannot be its own Group Project."),
            title=_("Invalid Group Project"),
        )


def _keep_the_parent_once_billing_exists(doc):
    """§4.5 — "A Sub Project cannot be re-linked to a different Group Project
    once any transaction exists against it." Moving it would silently rewrite
    which Group Project past revenue rolls up to."""
    before = doc.get_doc_before_save()
    if not before:
        return

    was = before.get("custom_group_project")
    now = doc.get("custom_group_project")
    if not was or was == now:
        return

    if has_billing_history(doc.name):
        frappe.throw(
            _(
                "{0} has already been billed under Group Project {1}, so it "
                "cannot be moved to another Group Project — the revenue "
                "already reported under {1} would change. Create a new Sub "
                "Project under the new Group Project instead."
            ).format(doc.name, was),
            title=_("Group Project is locked"),
        )


def _keep_the_group_flag_while_sub_projects_exist(doc):
    """Unticking Is Group Project would orphan every Sub Project under it."""
    before = doc.get_doc_before_save()
    if not before:
        return
    if not before.get("custom_is_group_project") or doc.get("custom_is_group_project"):
        return

    children = sub_projects_of(doc.name)
    if children:
        frappe.throw(
            _(
                "{0} still has {1} Sub Project(s) under it: {2}. Move them to "
                "another Group Project before unticking Is Group Project."
            ).format(doc.name, len(children), ", ".join(children[:5])),
            title=_("Group Project is in use"),
        )
