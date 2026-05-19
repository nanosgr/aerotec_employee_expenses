from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    advance_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de anticipos de sueldo",
        config_parameter="aerotec_employee_expenses.advance_account_id",
        help="Cuenta contable que se debita al crear un anticipo y se acredita al rendir los gastos.",
    )
