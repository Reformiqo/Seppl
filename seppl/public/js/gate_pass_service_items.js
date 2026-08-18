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
    },

    // A row added after the Manifest No was typed would otherwise start blank.
    custom_service_items_add: function (frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "custom_manifest_no", frm.doc.manifest_no);
    },
    // Tell the server which Gate Pass the invoice is being raised for.
    //
    // detox's `gate_pass.js` points Create → Sales Invoice at the SALES
    // ORDER mapper, so the Gate Pass is never read and its service charges
    // never reach the invoice. seppl wraps that mapper — but the wrapper
    // sits in front of EVERY Sales Order → Sales Invoice on the site, so it
    // stays inert unless a caller names a Gate Pass. This is the caller
    // that names one; invoices raised from the Sales Order form are
    // untouched.
    //
    // Same button, same mapper, same source — only `args` is added, so the
    // Sales Order behaviour users already know is unchanged.
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
