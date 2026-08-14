app_name = "seppl"
app_title = "Seppl"
app_publisher = "Reformiqo"
app_description = "This app contains details specific to the SEPPL site."
app_email = "consultant.reformiqo@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "seppl",
# 		"logo": "/assets/seppl/logo.png",
# 		"title": "Seppl",
# 		"route": "/seppl",
# 		"has_permission": "seppl.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/seppl/css/seppl.css"
# app_include_js = "/assets/seppl/js/seppl.js"

# include js, css files in header of web template
# web_include_css = "/assets/seppl/css/seppl.css"
# web_include_js = "/assets/seppl/js/seppl.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "seppl/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "seppl/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "seppl.utils.jinja_methods",
# 	"filters": "seppl.utils.jinja_filters"
# }

# Fixtures
# --------
# Customisations built for the SEPPL site are tagged with the "Seppl"
# module so `bench export-fixtures` picks them up here rather than into
# whichever app happens to own the doctype.
#
# This list is the single source of truth for SEPPL's schema: build the
# field in the UI, set its Module to "Seppl", run `bench export-fixtures`
# and commit the JSON. Do NOT also declare the same field in Python —
# after_migrate runs AFTER the fixture sync, so a code definition would
# silently overwrite whatever was last exported.

fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Seppl"]]},
]

# Installation
# ------------

# before_install = "seppl.install.before_install"
# after_install = "seppl.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "seppl.uninstall.before_uninstall"
# after_uninstall = "seppl.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "seppl.utils.before_app_install"
# after_app_install = "seppl.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "seppl.utils.before_app_uninstall"
# after_app_uninstall = "seppl.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "seppl.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "seppl.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		# Resolve a Gate Pass for any row that carries a Manifest No but
		# no Gate Pass yet — invoices predating the picker stamp, or an
		# ERPNext release that maps through some other core method.
		"before_validate": "seppl.overrides.sales_invoice.before_validate",
		# Back-link every Gate Pass billed here as soon as the DRAFT is
		# saved, not only at submit: the picker hides Gate Passes that
		# already carry a sales_invoice, so linking at save time is what
		# stops the same Gate Pass being pulled into a second draft.
		# Frappe runs on_update before on_submit, so submit is covered.
		"on_update": "seppl.overrides.sales_invoice.on_update",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"seppl.tasks.all"
# 	],
# 	"daily": [
# 		"seppl.tasks.daily"
# 	],
# 	"hourly": [
# 		"seppl.tasks.hourly"
# 	],
# 	"weekly": [
# 		"seppl.tasks.weekly"
# 	],
# 	"monthly": [
# 		"seppl.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "seppl.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "seppl.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------

# The "Get Items From → Gate Pass" picker on Sales Invoice posts to core's
# `map_docs`, which loops the selected Gate Passes through the mapper one
# at a time. Wrapping it is how SEPPL gets inside that loop to stamp the
# source Gate Pass on each mapped row — the mapper itself belongs to
# detox_waste_management and is not ours to edit. Every other mapping on
# the site is handed straight back to the core implementation.
override_whitelisted_methods = {
	"frappe.model.mapper.map_docs": "seppl.overrides.gate_pass_mapper.map_docs",
}

#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "seppl.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["seppl.utils.before_request"]
# after_request = ["seppl.utils.after_request"]

# Job Events
# ----------
# before_job = ["seppl.utils.before_job"]
# after_job = ["seppl.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"seppl.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
