var SEPPL_SERVICE_TABLE = "custom_service_items";

frappe.ui.form.on("Gate Pass", {    
    setup: function (frm) {
        frm.set_query("item_code", SEPPL_SERVICE_TABLE, function () {
            return { filters: { is_stock_item: 0 } };
        });
    },

    manifest_no: function (frm) {
        (frm.doc[SEPPL_SERVICE_TABLE] || []).forEach(function (row) {
            frappe.model.set_value(
                row.doctype, row.name, "custom_manifest_no", frm.doc.manifest_no
            );
        });
    }
});


frappe.ui.form.on("Gate Pass Item", {
    custom_service_items_add: function (frm, cdt, cdn) {
        console.log('added')
        frappe.model.set_value(cdt, cdn, "custom_manifest_no", frm.doc.manifest_no);
    },
});
