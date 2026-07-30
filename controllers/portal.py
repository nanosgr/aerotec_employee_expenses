import base64

from odoo import http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request, route
from odoo.addons.portal.controllers.portal import CustomerPortal


class EmployeeExpensePortal(CustomerPortal):

    def _get_employee(self):
        """Devuelve el hr.employee del usuario actual, o None si no tiene uno asociado."""
        employee = request.env["hr.employee"].sudo().search(
            [("user_id", "=", request.env.uid)], limit=1
        )
        return employee or None

    def _get_allowed_expense_accounts(self, employee):
        """Cuentas de gasto que el empleado puede elegir en el portal, según lo
        configurado en Ajustes > Contabilidad. Si la empresa no configuró
        ninguna, se permiten todas las cuentas de tipo gasto de esa empresa."""
        company = employee.company_id or request.env.company
        allowed = company.sudo().expense_portal_allowed_account_ids
        if allowed:
            return allowed.sorted(key=lambda a: a.code or "")
        return request.env["account.account"].sudo().search(
            [
                ("account_type", "like", "expense"),
                ("company_ids", "in", company.id),
            ],
            order="code",
        )

    def _check_report_access(self, report_id, employee):
        """
        Verifica que la rendición exista y pertenezca al empleado.
        Devuelve el reporte en sudo (para renderizado) o None si no tiene acceso.
        La verificación de propiedad se hace sin sudo para respetar las ir.rules.
        """
        report = request.env["aerotec.expense.report"].browse(report_id)
        if not report.exists() or report.employee_id.id != employee.id:
            return None
        return report.sudo()

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "expense_count" in counters:
            employee = self._get_employee()
            if employee:
                values["expense_count"] = request.env["aerotec.expense.report"].sudo().search_count(
                    [("employee_id", "=", employee.id)]
                )
            else:
                values["expense_count"] = 0
        return values

    @route(["/my/expenses"], type="http", auth="user", website=True)
    def portal_expenses_list(self, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.render(
                "aerotec_employee_expenses.portal_no_employee",
                {"page_name": "expenses"},
            )

        reports = request.env["aerotec.expense.report"].sudo().search(
            [("employee_id", "=", employee.id)],
            order="date desc, id desc",
        )
        advance = request.env["aerotec.employee.advance"].sudo().search(
            [("employee_id", "=", employee.id), ("state", "=", "confirmed")],
            limit=1,
        )

        return request.render(
            "aerotec_employee_expenses.portal_my_expenses",
            {
                "page_name": "expenses",
                "employee": employee,
                "reports": reports,
                "active_advance": advance,
            },
        )

    @route(["/my/expenses/new"], type="http", auth="user", website=True, methods=["POST"])
    def portal_expense_new(self, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/my/expenses")

        advance = request.env["aerotec.employee.advance"].sudo().search(
            [("employee_id", "=", employee.id), ("state", "=", "confirmed")],
            limit=1,
        )
        if not advance:
            return request.redirect("/my/expenses")

        if advance.expense_report_id:
            return request.redirect("/my/expenses/%d" % advance.expense_report_id.id)

        report = request.env["aerotec.expense.report"].sudo().create(
            {"advance_id": advance.id}
        )
        advance.write({"expense_report_id": report.id})
        return request.redirect("/my/expenses/%d" % report.id)

    @route(["/my/expenses/<int:report_id>"], type="http", auth="user", website=True)
    def portal_expense_detail(self, report_id, error=None, error_message=None, form_data=None, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/my/expenses")

        report = self._check_report_access(report_id, employee)
        if not report:
            return request.redirect("/my/expenses")

        expense_accounts = self._get_allowed_expense_accounts(employee)

        return request.render(
            "aerotec_employee_expenses.portal_expense_detail",
            {
                "page_name": "expenses",
                "employee": employee,
                "report": report,
                "expense_accounts": expense_accounts,
                "error": error or {},
                "error_message": error_message or [],
                "form_data": form_data or {},
            },
        )

    @route(
        ["/my/expenses/<int:report_id>/add-line"],
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_expense_add_line(self, report_id, **post):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/my/expenses")

        report = self._check_report_access(report_id, employee)
        if not report or report.state != "draft":
            return request.redirect("/my/expenses")

        error = {}
        error_message = []

        name = post.get("name", "").strip()
        amount_str = post.get("amount", "0").replace(",", ".").strip()
        date = post.get("date", "")
        expense_account_id = int(post.get("expense_account_id", 0) or 0)
        notes = post.get("notes", "").strip()

        expense_accounts = self._get_allowed_expense_accounts(employee)

        if not name:
            error["name"] = True
            error_message.append(_("La descripción es obligatoria."))
        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            error["amount"] = True
            error_message.append(_("El monto debe ser un número mayor a cero."))
            amount = 0.0
        if not date:
            error["date"] = True
            error_message.append(_("La fecha es obligatoria."))
        if not expense_account_id:
            error["expense_account_id"] = True
            error_message.append(_("La cuenta de gasto es obligatoria."))
        elif expense_account_id not in expense_accounts.ids:
            error["expense_account_id"] = True
            error_message.append(_("La cuenta de gasto seleccionada no está habilitada."))

        if error:
            return request.render(
                "aerotec_employee_expenses.portal_expense_detail",
                {
                    "page_name": "expenses",
                    "employee": employee,
                    "report": report,
                    "expense_accounts": expense_accounts,
                    "error": error,
                    "error_message": error_message,
                    "form_data": post,
                },
            )

        line = request.env["aerotec.expense.line"].sudo().create(
            {
                "report_id": report.id,
                "name": name,
                "amount": amount,
                "date": date,
                "expense_account_id": expense_account_id,
                "notes": notes,
            }
        )

        attachments = request.httprequest.files.getlist("attachments")
        attachment_ids = []
        for attachment_file in attachments:
            if attachment_file and attachment_file.filename:
                data = base64.b64encode(attachment_file.read())
                att = request.env["ir.attachment"].sudo().create(
                    {
                        "name": attachment_file.filename,
                        "datas": data,
                        "res_model": "aerotec.expense.line",
                        "res_id": line.id,
                    }
                )
                attachment_ids.append((4, att.id))
        if attachment_ids:
            line.write({"attachment_ids": attachment_ids})

        return request.redirect("/my/expenses/%d" % report_id)

    @route(
        ["/my/expenses/<int:report_id>/line/<int:line_id>/delete"],
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_expense_delete_line(self, report_id, line_id, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/my/expenses")

        report = self._check_report_access(report_id, employee)
        if not report or report.state != "draft":
            return request.redirect("/my/expenses/%d" % report_id)

        line = request.env["aerotec.expense.line"].sudo().browse(line_id)
        if line.exists() and line.report_id.id == report_id:
            line.unlink()

        return request.redirect("/my/expenses/%d" % report_id)

    @route(
        ["/my/expenses/<int:report_id>/submit"],
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_expense_submit(self, report_id, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.redirect("/my/expenses")

        report = self._check_report_access(report_id, employee)
        if not report or report.state != "draft":
            return request.redirect("/my/expenses/%d" % report_id)

        try:
            report.action_submit()
        except (UserError, ValidationError) as e:
            expense_accounts = self._get_allowed_expense_accounts(employee)
            return request.render(
                "aerotec_employee_expenses.portal_expense_detail",
                {
                    "page_name": "expenses",
                    "employee": employee,
                    "report": report,
                    "expense_accounts": expense_accounts,
                    "error": {},
                    "error_message": [str(e)],
                    "form_data": {},
                },
            )

        return request.redirect("/my/expenses/%d" % report_id)
