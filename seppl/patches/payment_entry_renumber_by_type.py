import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.rename_doc import rename_doc

RENAMED_LOG_TITLE = "Payment Entry rename - renamed"
FAILED_LOG_TITLE = "Payment Entry rename - failed"

PAYMENT_ENTRY_DOCTYPE = "Payment Entry"
INTERNAL_TRANSFER_SERIES = "ACC-INT-.YYYY.-"


def execute():
	add_internal_transfer_series()
	receive_renamed, receive_failed = rename_receive_entries()
	transfer_renamed, transfer_failed = rename_internal_transfer_entries()
	pay_renamed, pay_failed = rename_pay_entries()
	amended_renamed, amended_failed = rename_amended_entries()

	write_log(
		RENAMED_LOG_TITLE,
		"These Payment Entries were renamed:",
		receive_renamed + transfer_renamed + pay_renamed + amended_renamed,
	)

	write_log(
		FAILED_LOG_TITLE,
		"These Payment Entries were NOT renamed:",
		receive_failed + transfer_failed + pay_failed + amended_failed,
	)

	frappe.db.commit()


def add_internal_transfer_series():
	field = frappe.get_meta(PAYMENT_ENTRY_DOCTYPE).get_field("naming_series")
	options = (field.options or "").split("\n")

	if INTERNAL_TRANSFER_SERIES in options:
		return

	options.append(INTERNAL_TRANSFER_SERIES)

	make_property_setter(
		PAYMENT_ENTRY_DOCTYPE,
		"naming_series",
		"options",
		"\n".join(options),
		"Text",
		validate_fields_for_doctype=False,
	)


def rename_receive_entries():
	payment_entries = frappe.get_all(
		PAYMENT_ENTRY_DOCTYPE,
		filters={
			"payment_type": "Receive",
			"name": ["like", "ACC-PAY%"],
			"amended_from": ["is", "not set"],
		},
		fields=["name", "creation"],
		order_by="creation asc",
	)

	return rename_entries(
		payment_entries,
		"ACC-REC-2026-",
	)


def rename_internal_transfer_entries():
	payment_entries = frappe.get_all(
		PAYMENT_ENTRY_DOCTYPE,
		filters={
			"payment_type": "Internal Transfer",
			"amended_from": ["is", "not set"],
		},
		fields=["name", "creation"],
		order_by="creation asc",
	)

	return rename_entries(
		payment_entries,
		"ACC-INT-2026-",
	)


def rename_pay_entries():
	payment_entries = frappe.get_all(
		PAYMENT_ENTRY_DOCTYPE,
		filters={
			"payment_type": "Pay",
			"amended_from": ["is", "not set"],
		},
		fields=["name", "creation"],
		order_by="creation asc",
	)

	return rename_entries(
		payment_entries,
		"ACC-PAY-2026-",
	)


def rename_amended_entries():
	# Runs after the parents have moved. rename_doc has already repointed
	# `amended_from` to the parent's new name, so the new name is just that
	# plus the counter from the amendment's own name.
	amendments = frappe.get_all(
		PAYMENT_ENTRY_DOCTYPE,
		filters={
			"amended_from": ["is", "set"],
		},
		fields=["name", "amended_from"],
		order_by="creation asc",
	)

	renamed = []
	failures = []

	for amendment in amendments:
		counter = amendment.name.rsplit("-", 1)[-1]
		new_name = f"{amendment.amended_from}-{counter}"

		if amendment.name == new_name:
			continue

		print(f"Renaming {amendment.name} -> {new_name}")

		try:
			rename_doc(
				PAYMENT_ENTRY_DOCTYPE,
				amendment.name,
				new_name,
				force=True,
			)

			renamed.append(f"{amendment.name} -> {new_name}")

		except Exception:
			frappe.db.rollback()

			failures.append(f"{amendment.name} -> {new_name}: {frappe.get_traceback()}")
			break

	return renamed, failures


def rename_entries(payment_entries, prefix):
	renamed = []
	failures = []

	for idx, payment_entry in enumerate(payment_entries, start=1):
		old_name = payment_entry.name
		new_name = f"{prefix}{idx:05d}"

		if old_name == new_name:
			continue

		print(f"Renaming {old_name} -> {new_name}")

		try:
			rename_doc(
				PAYMENT_ENTRY_DOCTYPE,
				old_name,
				new_name,
				force=True,
			)

			renamed.append(f"{old_name} -> {new_name}")

		except Exception:
			frappe.db.rollback()

			failures.append(f"{old_name} -> {new_name}: {frappe.get_traceback()}")
			break

	return renamed, failures


def write_log(title, heading, lines):
	if lines:
		frappe.log_error(
			title=title,
			message=f"{heading}\n\n" + "\n".join(lines),
		)
