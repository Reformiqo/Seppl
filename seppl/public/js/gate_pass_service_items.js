var SEPPL_SERVICE_TABLE = "custom_service_items";
var SEPPL_SERVICE_DOCTYPE = "Gate Pass Service Item";
var SEPPL_PRICE_LIST = "custom_price_list";

// Gate Pass is not an ERPNext transaction, so its service charges are priced
// under the invoice they end up billed on. That is what makes ERPNext pick a
// selling vs a buying rate card, and what lets invoice-scoped Pricing Rules
// match at all. Everything below is the same call a Sales Invoice form makes.
function seppl_selling(frm) {
    return frm.doc.transaction_type !== "Outbound (Waste Dispatch)";
}

function seppl_price_list_context(frm) {
    var selling = seppl_selling(frm);
    return {
        doctype: selling ? "Sales Invoice" : "Purchase Invoice",
        party_type: selling ? "Customer" : "Supplier",
        party: selling ? frm.doc.customer : frm.doc.supplier,
        order_doctype: selling ? "Sales Order" : "Purchase Order",
        order: selling ? frm.doc.sales_order : frm.doc.purchase_order,
        field: selling ? "selling_price_list" : "buying_price_list",
    };
}

function seppl_set_default_price_list(frm) {
    var ctx = seppl_price_list_context(frm);

    var from_party = function () {
        if (!ctx.party) return;
        frappe.call({
            method: "erpnext.accounts.party.get_party_details",
            args: {
                party: ctx.party,
                party_type: ctx.party_type,
                company: frm.doc.company,
                posting_date: frm.doc.date,
                doctype: ctx.doctype,
                fetch_payment_terms_template: 0,
            },
            callback: function (r) {
                // A party with no default must not wipe a hand-picked list.
                var price_list = (r.message || {})[ctx.field];
                if (price_list) frm.set_value(SEPPL_PRICE_LIST, price_list);
            },
        });
    };

    // The linked order's own rate card wins — on this site it is the contract's.
    if (!ctx.order) return from_party();
    frappe.db.get_value(ctx.order_doctype, ctx.order, ctx.field).then(function (r) {
        var price_list = (r.message || {})[ctx.field];
        if (price_list) frm.set_value(SEPPL_PRICE_LIST, price_list);
        else from_party();
    });
}

// Also wired straight to header fields, and Frappe hands every handler
// (frm, doctype, name) — so anything but an explicit row list means "all rows".
function seppl_price_service_rows(frm, rows) {
    rows = (Array.isArray(rows) ? rows : frm.doc[SEPPL_SERVICE_TABLE] || []).filter(function (row) {
        return row.item_code;
    });
    if (!rows.length || !frm.doc[SEPPL_PRICE_LIST]) return;

    // ERPNext falls back from the row's UOM to the item's stock UOM only when
    // stock_uom is in the payload. A Sales Order row carries it as a field;
    // ours does not, and this table's UOM defaults to "Tonne" while every Item
    // Price here is in the item's stock UOM — so without this every rate comes
    // back 0. Looked up rather than stored so old rows price correctly too.
    frappe.db
        .get_list("Item", {
            filters: {
                name: [
                    "in",
                    rows.map(function (row) {
                        return row.item_code;
                    }),
                ],
            },
            fields: ["name", "stock_uom"],
            limit: 0,
        })
        .then(function (items) {
            var stock_uom = {};
            (items || []).forEach(function (item) {
                stock_uom[item.name] = item.stock_uom;
            });
            seppl_apply_price_list(frm, rows, stock_uom);
        });
}

function seppl_apply_price_list(frm, rows, stock_uom) {
    var ctx = seppl_price_list_context(frm);
    frappe.call({
        method: "erpnext.stock.get_item_details.apply_price_list",
        args: {
            ctx: {
                doctype: ctx.doctype,
                company: frm.doc.company,
                customer: seppl_selling(frm) ? ctx.party : null,
                supplier: seppl_selling(frm) ? null : ctx.party,
                price_list: frm.doc[SEPPL_PRICE_LIST],
                // Service charges are billed in company currency. Leaving
                // price_list_currency and plc_conversion_rate out lets ERPNext
                // derive them, so a price list in another currency converts.
                conversion_rate: 1.0,
                transaction_date: frm.doc.date,
                ignore_pricing_rule: cint(frm.doc.custom_ignore_pricing_rule),
                // Qty is sent because a Pricing Rule's slabs and an Item
                // Price's packing unit are both read against it.
                items: rows.map(function (row) {
                    return {
                        item_code: row.item_code,
                        uom: row.uom,
                        stock_uom: stock_uom[row.item_code],
                        qty: flt(row.qty),
                    };
                }),
            },
        },
        callback: function (r) {
            $.each((r.message || {}).children || [], function (i, details) {
                // A Pricing Rule that fixes the rate outright wins; otherwise
                // it is the price list rate less the rule's discount.
                var rate =
                    flt(details.rate) ||
                    flt(details.price_list_rate) * (1 - flt(details.discount_percentage) / 100);
                // A price list that says nothing must not wipe a typed rate.
                if (rate) frappe.model.set_value(SEPPL_SERVICE_DOCTYPE, rows[i].name, "rate", rate);
            });
        },
    });
}

function seppl_price_row(frm, cdt, cdn) {
    seppl_price_service_rows(frm, [locals[cdt][cdn]]);
}

frappe.ui.form.on("Gate Pass", {
    setup: function (frm) {
        frm.set_query("item_code", SEPPL_SERVICE_TABLE, function () {
            return { filters: { is_stock_item: 0 } };
        });

        // A Price List is either a selling or a buying rate card, and which
        // one applies flips with the transaction type.
        frm.set_query(SEPPL_PRICE_LIST, function () {
            var filters = { enabled: 1 };
            filters[seppl_selling(frm) ? "selling" : "buying"] = 1;
            return { filters: filters };
        });
    },

    manifest_no: function (frm) {
        (frm.doc[SEPPL_SERVICE_TABLE] || []).forEach(function (row) {
            frappe.model.set_value(row.doctype, row.name, "manifest_no", frm.doc.manifest_no);
        });
        (frm.doc["items"] || []).forEach(function (row) {
            frappe.model.set_value(row.doctype, row.name, "custom_manifest_no", frm.doc.manifest_no);
        });
    },

    // The party is cleared on a type switch, so a price list resolved for the
    // old side would be a selling card on a buying document.
    transaction_type: function (frm) {
        frm.set_value(SEPPL_PRICE_LIST, "");
    },

    customer: seppl_set_default_price_list,
    supplier: seppl_set_default_price_list,
    sales_order: seppl_set_default_price_list,
    purchase_order: seppl_set_default_price_list,

    custom_price_list: seppl_price_service_rows,
    custom_ignore_pricing_rule: seppl_price_service_rows,

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


frappe.ui.form.on('Gate Pass Item', {
    items_add: function (frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "custom_manifest_no", frm.doc.manifest_no);
    },
})


frappe.ui.form.on("Gate Pass Service Item", {
    custom_service_items_add: function (frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "manifest_no", frm.doc.manifest_no);
    },

    item_code: seppl_price_row,
    qty: seppl_price_row,
    uom: seppl_price_row,
});
