{
    "name": "Aerotec - Gastos de Empleados",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Expenses",
    "summary": "Anticipos de sueldo y rendición de gastos para empleados en portal",
    "author": "Sebastian Rios",
    "license": "LGPL-3",
    "depends": ["hr", "account", "portal", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequences.xml",
        "data/mail_templates.xml",
        "views/hr_employee_views.xml",
        "views/aerotec_employee_advance_views.xml",
        "views/aerotec_expense_report_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
        "templates/portal_layout.xml",
        "templates/portal_expense_detail.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "aerotec_employee_expenses/static/src/js/portal.js",
        ],
    },
    "installable": True,
    "auto_install": False,
}
