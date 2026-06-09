from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class AerotecEmployeeAdvance(models.Model):
    _name = "aerotec.employee.advance"
    _description = "Anticipo de Sueldo"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        readonly=True,
        default="Nuevo",
        copy=False,
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Monto del anticipo",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    payment_method = fields.Selection(
        [
            ("cash", "Efectivo"),
            ("mercado_pago", "Mercado Pago"),
            ("corporate_card", "Tarjeta Corporativa"),
        ],
        string="Medio de pago",
        required=True,
        tracking=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de origen",
        required=True,
        tracking=True,
        help="Diario contable que representa la fuente del dinero (caja, Mercado Pago, tarjeta corporativa).",
    )
    advance_account_id = fields.Many2one(
        "account.account",
        string="Cuenta de anticipos",
        required=True,
        tracking=True,
        help="Cuenta contable de Anticipos de Sueldo. Se toma de la configuración si no se especifica.",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmado"),
            ("settled", "Liquidado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    account_move_id = fields.Many2one(
        "account.move",
        string="Asiento contable",
        readonly=True,
        copy=False,
    )
    expense_report_id = fields.Many2one(
        "aerotec.expense.report",
        string="Rendición",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Observaciones")
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "aerotec.employee.advance"
                ) or "Nuevo"
            if not vals.get("advance_account_id"):
                config = self.env["ir.config_parameter"].sudo()
                account_id = config.get_param("aerotec_employee_expenses.advance_account_id")
                if account_id:
                    vals["advance_account_id"] = int(account_id)
        return super().create(vals_list)

    @api.constrains("employee_id", "state")
    def _check_single_active_advance(self):
        for rec in self:
            if rec.state == "confirmed":
                domain = [
                    ("employee_id", "=", rec.employee_id.id),
                    ("state", "=", "confirmed"),
                    ("id", "!=", rec.id),
                ]
                if self.search_count(domain):
                    raise ValidationError(
                        _(
                            "El empleado %(name)s ya tiene un anticipo activo. "
                            "Debe liquidar el anticipo existente antes de crear uno nuevo.",
                            name=rec.employee_id.name,
                        )
                    )

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec._check_single_active_advance()
            move = rec._create_advance_move()
            rec.write({"state": "confirmed", "account_move_id": move.id})
            rec._send_advance_notification()

    def action_reset_draft(self):
        for rec in self:
            if rec.state != "confirmed":
                continue
            if rec.expense_report_id:
                raise UserError(
                    _("No se puede volver a borrador: ya existe una rendición asociada.")
                )
            if rec.account_move_id and rec.account_move_id.state == "posted":
                rec.account_move_id.button_draft()
                rec.account_move_id.button_cancel()
            rec.write({"state": "draft"})

    def _create_advance_move(self):
        self.ensure_one()
        journal = self.journal_id
        advance_account = self.advance_account_id
        if not advance_account:
            raise UserError(
                _("Configure la cuenta de anticipos de sueldo en Ajustes > Contabilidad.")
            )
        liquidity_account = journal.default_account_id
        if not liquidity_account:
            raise UserError(
                _(
                    "El diario '%(journal)s' no tiene cuenta por defecto configurada.",
                    journal=journal.name,
                )
            )
        employee_partner = self.employee_id.work_contact_id
        move_vals = {
            "journal_id": journal.id,
            "date": self.date,
            "ref": _("Anticipo %(name)s - %(employee)s", name=self.name, employee=self.employee_id.name),
            "line_ids": [
                (
                    0,
                    0,
                    {
                        "account_id": advance_account.id,
                        "name": _("Anticipo de sueldo - %(employee)s", employee=self.employee_id.name),
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": self.amount,
                        "credit": 0.0,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "account_id": liquidity_account.id,
                        "name": _("Anticipo de sueldo - %(employee)s", employee=self.employee_id.name),
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": 0.0,
                        "credit": self.amount,
                    },
                ),
            ],
        }
        move = self.env["account.move"].create(move_vals)
        move.action_post()
        return move

    def _send_advance_notification(self):
        self.ensure_one()
        template = self.env.ref(
            "aerotec_employee_expenses.mail_template_advance_confirmed",
            raise_if_not_found=False,
        )
        if template and self.employee_id.work_email:
            template.send_mail(self.id, force_send=True)

    def action_view_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento contable"),
            "res_model": "account.move",
            "res_id": self.account_move_id.id,
            "view_mode": "form",
        }
