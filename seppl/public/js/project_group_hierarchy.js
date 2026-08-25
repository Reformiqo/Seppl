// ABP2-I406 — the Group Project / Sub Project hierarchy on the Project form.
//
// Level 1 is a Group Project (`custom_is_group_project`); Level 2 names its
// parent in `custom_group_project`. Only a Level 1 project can be a parent,
// so that is all the lookup offers — the server refuses anything else
// (seppl.overrides.project), this just stops the user getting there.
//
// ES5 to match the rest of this app's form scripts.

frappe.ui.form.on("Project", {
    setup: function (frm) {
        // No self-exclusion here: a Group Project has this field hidden, and
        // a non-group can never appear in a list filtered to groups, so a
        // project can never be offered as its own parent. Adding it only put
        // the unsaved doc's temporary name in front of the user.
        // seppl.overrides.project still refuses one on the server.
        frm.set_query("custom_group_project", function () {
            return { filters: { custom_is_group_project: 1 } };
        });
    },

    // Ticking Is Group Project hides the parent field (depends_on) but does
    // not empty it. A value left behind there would trip the server's
    // "a Group Project cannot have a parent" guard from a field the user
    // can no longer see.
    custom_is_group_project: function (frm) {
        if (frm.doc.custom_is_group_project && frm.doc.custom_group_project) {
            frm.set_value("custom_group_project", "");
        }
    },
});
