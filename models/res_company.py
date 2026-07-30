from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    expense_portal_allowed_account_ids = fields.Many2many(
        "account.account",
        "aerotec_expense_allowed_account_rel",
        "company_id",
        "account_id",
        string="Cuentas de gasto habilitadas en portal",
        check_company=True,
        domain="[('account_type', 'like', 'expense')]",
        help="Cuentas contables que los empleados pueden elegir al cargar gastos desde el portal. "
        "Si no se selecciona ninguna, se permiten todas las cuentas de tipo gasto de la empresa.",
    )
