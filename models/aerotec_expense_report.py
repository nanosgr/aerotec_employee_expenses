from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AerotecExpenseReport(models.Model):
    _name = "aerotec.expense.report"
    _description = "Rendición de Gastos"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        readonly=True,
        default="Nueva",
        copy=False,
        tracking=True,
    )
    advance_id = fields.Many2one(
        "aerotec.employee.advance",
        string="Anticipo",
        required=True,
        tracking=True,
        domain=[("state", "=", "confirmed")],
        states={
            "submitted": [("readonly", True)],
            "approved": [("readonly", True)],
            "posted": [("readonly", True)],
        },
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        related="advance_id.employee_id",
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="advance_id.currency_id",
        store=True,
        readonly=True,
    )
    date = fields.Date(
        string="Fecha de rendición",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        states={
            "submitted": [("readonly", True)],
            "approved": [("readonly", True)],
            "posted": [("readonly", True)],
        },
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("submitted", "Enviada"),
            ("approved", "Aprobada"),
            ("posted", "Contabilizada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    line_ids = fields.One2many(
        "aerotec.expense.line",
        "report_id",
        string="Líneas de gasto",
        states={
            "submitted": [("readonly", True)],
            "approved": [("readonly", True)],
            "posted": [("readonly", True)],
        },
    )
    total_expenses = fields.Monetary(
        string="Total gastos",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    surplus_amount = fields.Monetary(
        string="Remanente a devolver",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
        help="Diferencia entre el anticipo y los gastos rendidos. Si es positivo, el empleado debe devolver ese monto.",
    )
    account_move_id = fields.Many2one(
        "account.move",
        string="Asiento contable",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Observaciones del empleado")
    rejection_reason = fields.Text(string="Motivo de rechazo", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company",
        related="advance_id.company_id",
        store=True,
        readonly=True,
    )

    @api.depends("line_ids.amount", "advance_id.amount")
    def _compute_totals(self):
        for rec in self:
            rec.total_expenses = sum(rec.line_ids.mapped("amount"))
            rec.surplus_amount = max(
                rec.advance_id.amount - rec.total_expenses, 0.0
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nueva") == "Nueva":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "aerotec.expense.report"
                ) or "Nueva"
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.line_ids:
                raise UserError(
                    _("Debe agregar al menos una línea de gasto antes de enviar la rendición.")
                )
            rec.write({"state": "submitted", "rejection_reason": False})
            rec._notify_manager_submitted()

    def action_approve(self):
        for rec in self:
            if rec.state != "submitted":
                continue
            rec.write({"state": "approved"})
            rec._notify_employee_approved()

    def action_reject(self, reason=None):
        for rec in self:
            if rec.state not in ("submitted", "approved"):
                continue
            rec.write({"state": "draft", "rejection_reason": reason or ""})
            rec._notify_employee_rejected()

    def action_post(self):
        for rec in self:
            if rec.state != "approved":
                continue
            move = rec._create_expense_move()
            rec.write({"state": "posted", "account_move_id": move.id})
            rec.advance_id.write({"state": "settled"})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ("submitted",):
                raise UserError(
                    _("Solo se pueden devolver a borrador las rendiciones en estado 'Enviada'.")
                )
            rec.write({"state": "draft"})

    def _create_expense_move(self):
        self.ensure_one()
        advance = self.advance_id
        advance_account = advance.advance_account_id
        journal = advance.journal_id
        employee_partner = self.employee_id.work_contact_id

        if not advance_account:
            raise UserError(
                _("El anticipo no tiene cuenta de anticipos de sueldo configurada.")
            )

        move_lines = []
        for line in self.line_ids:
            if not line.expense_account_id:
                raise UserError(
                    _(
                        "La línea '%(line)s' no tiene cuenta de gasto asignada.",
                        line=line.name,
                    )
                )
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": line.expense_account_id.id,
                        "name": line.name,
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": line.amount,
                        "credit": 0.0,
                        "date": line.date or self.date,
                    },
                )
            )

        total_gastos = self.total_expenses
        surplus = advance.amount - total_gastos

        if total_gastos > 0:
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": advance_account.id,
                        "name": _("Rendición %(name)s - gastos", name=self.name),
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": 0.0,
                        "credit": total_gastos,
                    },
                )
            )

        if surplus > 0:
            liquidity_account = journal.default_account_id
            if not liquidity_account:
                raise UserError(
                    _(
                        "El diario '%(journal)s' no tiene cuenta por defecto para registrar la devolución del remanente.",
                        journal=journal.name,
                    )
                )
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": liquidity_account.id,
                        "name": _("Devolución remanente %(name)s", name=self.name),
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": surplus,
                        "credit": 0.0,
                    },
                )
            )
            move_lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": advance_account.id,
                        "name": _("Rendición %(name)s - devolución remanente", name=self.name),
                        "partner_id": employee_partner.id if employee_partner else False,
                        "debit": 0.0,
                        "credit": surplus,
                    },
                )
            )

        move_vals = {
            "journal_id": journal.id,
            "date": self.date,
            "ref": _(
                "Rendición %(name)s - %(employee)s",
                name=self.name,
                employee=self.employee_id.name,
            ),
            "line_ids": move_lines,
        }
        move = self.env["account.move"].create(move_vals)
        move.action_post()
        return move

    def _notify_manager_submitted(self):
        self.ensure_one()
        template = self.env.ref(
            "aerotec_employee_expenses.mail_template_report_submitted",
            raise_if_not_found=False,
        )
        if template:
            template.send_mail(self.id, force_send=True)

    def _notify_employee_approved(self):
        self.ensure_one()
        template = self.env.ref(
            "aerotec_employee_expenses.mail_template_report_approved",
            raise_if_not_found=False,
        )
        if template and self.employee_id.work_email:
            template.send_mail(self.id, force_send=True)

    def _notify_employee_rejected(self):
        self.ensure_one()
        template = self.env.ref(
            "aerotec_employee_expenses.mail_template_report_rejected",
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
