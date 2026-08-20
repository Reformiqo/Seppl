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
                row.doctype, row.name, "manifest_no", frm.doc.manifest_no
            );
        });
    },

    refresh: function (frm) {
        if (frm.doc.docstatus !== 1) return;
        if (!frm.doc.sales_order || frm.doc.sales_invoice) return;
        if (frm.doc.transaction_type !== "Inbound (Waste Receipt)") return;

        frm.remove_custom_button(__("Create Sales Invoice"), __("Create"));
        frm.add_custom_button(
            __("Create Sales Invoice"),
            function () {
                frappe.model.open_mapped_doc({
                    method: "erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice",
                    frm: frm,
                    source_name: frm.doc.sales_order,
                    args: { gate_pass: frm.doc.name },
                });
            },
            __("Create")
        );
    },
});


frappe.ui.form.on("Gate Pass Service Item", {
    custom_service_items_add: function (frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "manifest_no", frm.doc.manifest_no);
    },
});