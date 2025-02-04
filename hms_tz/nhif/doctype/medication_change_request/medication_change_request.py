# -*- coding: utf-8 -*-
# Copyright (c) 2021, Aakvatech and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from hms_tz.nhif.api.healthcare_utils import (
    get_item_rate,
    get_warehouse_from_service_unit,
)
from hms_tz.hms_tz.doctype.patient_encounter.patient_encounter import get_quantity
from hms_tz.nhif.api.healthcare_utils import get_template_company_option
from hms_tz.nhif.api.patient_encounter import validate_stock_item


class MedicationChangeRequest(Document):
    def validate(self):
        self.title = "{0}/{1}".format(self.patient_encounter, self.delivery_note)
        if self.drug_prescription:
            for drug in self.drug_prescription:
                set_amount(self, drug)
                if not drug.quantity or drug.quantity == 0:
                    drug.quantity = get_quantity(drug)
                drug.delivered_quantity = drug.quantity - (drug.quantity_returned or 0)

                template_doc = get_template_company_option(drug.drug_code, self.company)
                drug.is_not_available_inhouse = template_doc.is_not_available
                if drug.is_not_available_inhouse == 1:
                    frappe.msgprint(
                        "NOTE: This healthcare service item, <b>"
                        + drug.drug_code + "</b>, is not available inhouse".format(
                            frappe.bold(drug.drug_code)
                    ))
                
                validate_restricted(self, drug)
    
    def before_insert(self):
        if self.patient_encounter:
            encounter_doc = get_patient_encounter_doc(self.patient_encounter)
            if not encounter_doc.insurance_coverage_plan:
                frappe.throw(frappe.bold("Cannot create medication change request for Cash Patient,\
                    Medication change request is only used for Insurance Patients"))
        
    def before_submit(self):
        for item in self.drug_prescription:
            validate_stock_item(
                    item.drug_code, 
                    item.quantity, 
                    self.company, 
                    item.doctype, 
                    item.healthcare_service_unit,
                    caller="unknown",
                    method="throw"
                )
    
    def on_submit(self):
        encounter_doc = self.update_encounter()
        self.update_delivery_note(encounter_doc)

    def update_encounter(self):
        doc = frappe.get_doc("Patient Encounter", self.patient_encounter)
        for row in doc.drug_prescription:
            frappe.delete_doc(
                row.doctype, row.name, force=1, ignore_permissions=True, for_reload=True
            )
        doc.reload()
        fields_to_clear = [
            "name",
            "owner",
            "creation",
            "modified",
            "modified_by",
            "docstatus",
            "amended_from",
            "amendment_date",
            "parentfield",
            "parenttype",
        ]
        for row in self.drug_prescription:
            if row.is_not_available_inhouse == 1:
                continue
            new_row = frappe.copy_doc(row).as_dict()
            for fieldname in fields_to_clear:
                new_row[fieldname] = None
            new_row["drug_prescription_created"] = 1
            doc.append("drug_prescription", new_row)
        doc.db_update_all()
        frappe.msgprint(
            _("Patient Encounter " + self.patient_encounter + " has been updated!"),
            alert=True,
        )
        return doc

    def update_delivery_note(self, encounter_doc):
        doc = frappe.get_doc("Delivery Note", self.delivery_note)
        doc.items = []
        for row in encounter_doc.drug_prescription:
            if row.prescribe or row.is_not_available_inhouse:
                continue
            item_code = frappe.get_value("Medication", row.drug_code, "item")
            is_stock, item_name = frappe.get_value(
                "Item", item_code, ["is_stock_item", "item_name"]
            )
            warehouse = get_warehouse_from_service_unit(row.healthcare_service_unit)
            if not is_stock:
                continue
            item = frappe.new_doc("Delivery Note Item")
            if not item:
                frappe.throw(
                    _("Could not create delivery note item for " + row.drug_code)
                )
            item.item_code = item_code
            item.item_name = item_name
            item.warehouse = warehouse
            item.qty = row.delivered_quantity or 1
            item.medical_code = row.medical_code
            item.rate = row.amount
            item.amount = row.amount * row.delivered_quantity
            item.reference_doctype = row.doctype
            item.reference_name = row.name
            item.is_restricted = row.is_restricted
            item.description = (
                row.drug_name
                + " for "
                + row.dosage
                + " for "
                + row.period
                + " with specific notes as follows: "
                + (row.comment or "No Comments")
            )
            doc.append("items", item)
        doc.save(ignore_permissions=True)
        frappe.msgprint(
            _("Delivery Note " + self.delivery_note + " has been updated!"), alert=True
        )


@frappe.whitelist()
def get_delivery_note(patient_encounter):
    d_list = frappe.get_all(
        "Delivery Note", filters={"reference_name": patient_encounter, "docstatus": 0}
    )
    if len(d_list):
        return d_list[0].name
    else:
        return ""


@frappe.whitelist()
def get_patient_encounter_name(delivery_note):
    doc = frappe.get_doc("Delivery Note", delivery_note)
    if doc.reference_doctype and doc.reference_name:
        if doc.reference_doctype == "Patient Encounter":
            return doc.reference_name
    return ""


@frappe.whitelist()
def get_patient_encounter_doc(patient_encounter):
    doc = frappe.get_doc("Patient Encounter", patient_encounter)
    return doc

def get_insurance_details(self):
    insurance_subscription, insurance_company = frappe.get_value(
        "Patient Appointment", self.appointment,
        ["insurance_subscription", "insurance_company"],
    )
    return insurance_subscription, insurance_company

def set_amount(self, item):
    insurance_subscription, insurance_company = get_insurance_details(self)

    item_code = frappe.get_value("Medication", item.drug_code, "item")
    item.amount = get_item_rate(
        item_code, self.company, insurance_subscription, insurance_company
    )

def validate_restricted(self, row):
    items = {}
    insurance_subscription, insurance_company = get_insurance_details(self)

    insurance_coverage_plan = frappe.get_value(
        "Healthcare Insurance Subscription",
        {"name" :insurance_subscription},
        "healthcare_insurance_coverage_plan"
    )
    if not insurance_coverage_plan:
        frappe.throw(_("Healthcare Insurance Coverage Plan is Not defiend"))
    
    today = frappe.utils.nowdate()
    service_coverage = frappe.get_all("Healthcare Service Insurance Coverage",
        filters={"is_active": 1, "start_date": ["<=", today],"end_date": [">=", today],
            "healthcare_service_template": row.drug_code, 
            "healthcare_insurance_coverage_plan": insurance_coverage_plan,
        }, fields=["name", "approval_mandatory_for_claim"],
    )
    if service_coverage:
        row.is_restricted = service_coverage[0].approval_mandatory_for_claim
    else:
        row.is_restricted = 0
    
