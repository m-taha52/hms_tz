// Copyright (c) 2016, Aakvatech and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Patient Time Oriented Report"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			//"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			//"default": frappe.datetime.get_today(),
			"reqd": 1
		}

	]
};
//"default": frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth() + 1