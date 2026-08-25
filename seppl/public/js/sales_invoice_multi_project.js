// ABP2-I406 — Sales Invoice: Group Project on the header, Sub Project and
// Cost Centre per line (BRD §4.3).
//
//   header  Group Project   picked here, and only here
//   line    Sub Project     picked per line, filtered to the header's Group
//   line    Group Project   read-only, inherited from the header (FR-03)
//   line    Cost Centre     defaults from the Sub Project master, overrideable
//
// The server (seppl.overrides.sales_invoice.validate_multi_project_mapping)
// is what actually enforces the rules; this is the part that makes them easy
// to follow — nothing here is a validation.
//
// Backward compatibility: every handler below returns early when the header
// has no Group Project, so a plain single-project invoice behaves exactly as
// it did before.
//
// ES5 to match the rest of this app's form scripts.

var SEPPL_MP_GROUP = "custom_group_project";

// Header dimensions that clear their column on the lines when emptied.
var SEPPL_MP_LABELS = { project: "Project", cost_center: "Cost Center" };

// FR-01 — only Level 1 projects, and only open ones.
function seppl_mp_group_project_query(frm) {
    var filters = { custom_is_group_project: 1, status: "Open" };
    if (frm.doc.company) filters.company = frm.doc.company;
    return { filters: filters };
}

// FR-05 — Sub Projects of the header's Group Project only. §4.5 also rules
// out closed and inactive ones.
function seppl_mp_sub_project_query(frm) {
    if (!frm.doc[SEPPL_MP_GROUP]) {
        // No Group Project on the header: this is an ordinary invoice, so
        // leave ERPNext's unfiltered Project lookup alone.
        return {};
    }
    var filters = {
        custom_group_project: frm.doc[SEPPL_MP_GROUP],
        status: "Open",
        is_active: "Yes",
    };
    if (frm.doc.company) filters.company = frm.doc.company;
    return { filters: filters };
}

// FR-03 — the line's Group Project is never typed; it mirrors the header.
function seppl_mp_stamp_rows(frm) {
    (frm.doc.items || []).forEach(function (row) {
        if (row[SEPPL_MP_GROUP] !== frm.doc[SEPPL_MP_GROUP]) {
            frappe.model.set_value(
                row.doctype, row.name, SEPPL_MP_GROUP, frm.doc[SEPPL_MP_GROUP]
            );
        }
    });
}

// Changing the Group Project invalidates any line pointing at a Sub Project
// of the old one. Clearing them beats letting the user hit a submit-time
// error on row 14 of 20.
function seppl_mp_drop_foreign_sub_projects(frm) {
    var group = frm.doc[SEPPL_MP_GROUP];
    var rows = (frm.doc.items || []).filter(function (row) {
        return row.project;
    });
    if (!group || !rows.length) return;

    var projects = rows.map(function (row) {
        return row.project;
    });
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Project",
            filters: [["name", "in", projects]],
            fields: ["name", "custom_group_project"],
            limit_page_length: projects.length,
        },
    }).then(function (r) {
        var owner = {};
        ((r && r.message) || []).forEach(function (project) {
            owner[project.name] = project.custom_group_project || "";
        });
        var dropped = [];
        rows.forEach(function (row) {
            // Anything that is not a Sub Project of this Group has to go —
            // both a Sub Project of a DIFFERENT Group, and (the common case)
            // the ordinary project the line inherited from its Sales Order
            // or Gate Pass, which belongs to no Group at all.
            if (owner[row.project] === group) return;
            dropped.push(row.idx + " (" + row.project + ")");
            frappe.model.set_value(row.doctype, row.name, "project", "");
            // Its Cost Centre came with it and means nothing here; picking
            // the Sub Project refills it from that project's default.
            frappe.model.set_value(row.doctype, row.name, "cost_center", "");
        });
        if (dropped.length) {
            frappe.show_alert({
                message: __("Cleared Sub Project and Cost Centre on row(s) {0} — pick a Sub Project of {1}.", [dropped.join(", "), group]),
                indicator: "orange",
            });
        }
    });
}

// Clearing a dimension on the header clears it on every line.
//
// Requested for the multi-project flow, where a line arrives carrying the
// project and cost centre of the Sales Order or Gate Pass it was pulled
// from: emptying the header field is how the user says "these are per-line
// now". Applies to any Sales Invoice, not only multi-project ones.
//
// Only a value that WAS set and is now empty triggers this. Setting the
// header to a new value is left to ABP2-I194's dimension_sync, and a
// programmatic reset of an already-empty field does nothing.
function seppl_mp_clear_rows_with_header(frm, fieldname) {
    var key = "__seppl_mp_last_" + fieldname;
    var previous = frm[key];
    frm[key] = frm.doc[fieldname] || "";

    if (frm.doc[fieldname] || !previous) return;

    var cleared = [];
    (frm.doc.items || []).forEach(function (row) {
        if (!row[fieldname]) return;
        cleared.push(String(row.idx));
        frappe.model.set_value(row.doctype, row.name, fieldname, "");
    });
    if (cleared.length) {
        frappe.show_alert({
            message: __("Cleared {0} on row(s) {1}.", [
                __(SEPPL_MP_LABELS[fieldname] || fieldname),
                cleared.join(", "),
            ]),
            indicator: "orange",
        });
    }
}

// Seed the remembered values so the first edit compares against what the
// form actually opened with.
function seppl_mp_seed_header_memory(frm) {
    frm.__seppl_mp_last_project = frm.doc.project || "";
    frm.__seppl_mp_last_cost_center = frm.doc.cost_center || "";
}

frappe.ui.form.on("Sales Invoice", {
    setup: function (frm) {
        frm.set_query(SEPPL_MP_GROUP, function () {
            return seppl_mp_group_project_query(frm);
        });
        frm.set_query("project", "items", function () {
            return seppl_mp_sub_project_query(frm);
        });
    },

    onload: function (frm) {
        seppl_mp_seed_header_memory(frm);
    },

    refresh: function (frm) {
        seppl_mp_seed_header_memory(frm);
    },

    project: function (frm) {
        seppl_mp_clear_rows_with_header(frm, "project");
    },

    cost_center: function (frm) {
        seppl_mp_clear_rows_with_header(frm, "cost_center");
    },

    custom_group_project: function (frm) {
        seppl_mp_drop_foreign_sub_projects(frm);
        seppl_mp_stamp_rows(frm);
    },

    // Grid add/remove fire on the parent, not on the child doctype.
    items_add: function (frm, cdt, cdn) {
        if (!frm.doc[SEPPL_MP_GROUP]) return;
        frappe.model.set_value(cdt, cdn, SEPPL_MP_GROUP, frm.doc[SEPPL_MP_GROUP]);
    },
});

frappe.ui.form.on("Sales Invoice Item", {
    project: function (frm, cdt, cdn) {
        if (!frm.doc[SEPPL_MP_GROUP]) return;

        var row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, SEPPL_MP_GROUP, frm.doc[SEPPL_MP_GROUP]);
        if (!row.project) return;

        // FR-04 — default the Cost Centre from the Sub Project master. The
        // user picked a different Sub Project, so its default replaces the
        // previous one; they stay free to change it afterwards.
        frappe.db.get_value("Project", row.project, "cost_center").then(function (r) {
            var cost_center = r && r.message ? r.message.cost_center : null;
            if (cost_center) {
                frappe.model.set_value(cdt, cdn, "cost_center", cost_center);
            }
        });
    },
});
