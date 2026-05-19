from odoo import fields, models


class AerotecExpenseLine(models.Model):
    _name = "aerotec.expense.line"
    _description = "Línea de Gasto"
    _order = "date, id"

    report_id = fields.Many2one(
        "aerotec.expense.report",
        string="Rendición",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        related="report_id.employee_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="report_id.currency_id",
        store=True,
        readonly=True,
    )
    date = fields.Date(
        string="Fecha del gasto",
        required=True,
        default=fields.Date.context_today,
    )
    name = fields.Char(string="Descripción", required=True)
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de gasto",
        required=True,
    )
    vendor_bill_id = fields.Many2one(
        "account.move",
        string="Factura de proveedor",
        domain=[("move_type", "=", "in_invoice")],
        help="Factura de proveedor formal asociada a este comprobante. La completa el contador.",
    )
    notes = fields.Text(string="Notas")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "aerotec_expense_line_attachment_rel",
        "line_id",
        "attachment_id",
        string="Comprobantes adjuntos",
    )
    attachment_count = fields.Integer(
        string="Cantidad de adjuntos",
        compute="_compute_attachment_count",
    )

    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)
