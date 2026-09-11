frappe.query_reports["SEPPL Delivery Challan Report"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            reqd: 1,
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.month_start(),
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "warehouse",
            label: __("Plant / Warehouse"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                var company = frappe.query_report.get_filter_value("company");
                return frappe.db.get_link_options(
                    "Warehouse", txt, company ? { company: company } : {}
                );
            },
        },
        {
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                return frappe.db.get_link_options("Customer", txt);
            },
        },
        {
            fieldname: "item_code",
            label: __("Item (Material)"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                return frappe.db.get_link_options("Item", txt);
            },
        },
        {
            fieldname: "sales_order",
            label: __("Sales Order"),
            fieldtype: "Link",
            options: "Sales Order",
        },
        {
            fieldname: "invoice_status",
            label: __("Invoice Status"),
            fieldtype: "Select",
            options: ["All", "Billed", "Unbilled"].join("\n"),
            default: "All",
        },
        {
            fieldname: "document_type",
            label: __("Document Type"),
            fieldtype: "Select",
            options: ["", "Invoice", "Credit Note", "Debit Note"],
            default: "",
        },
        {
            fieldname: "transporter",
            label: __("Transporter"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                return frappe.db.get_link_options("Supplier", txt, { is_transporter: 1 });
            },
        },
        {
            fieldname: "vehicle_no",
            label: __("Vehicle No."),
            fieldtype: "Data",
        },
    ],
};
