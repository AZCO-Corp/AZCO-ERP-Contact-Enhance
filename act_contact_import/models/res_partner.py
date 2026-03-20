from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    act_contact_id = fields.Char(
        string="ACT Contact ID",
        copy=False,
        index=True,
        help="Unique identifier from the ACT! CRM database",
    )
    act_company_id = fields.Char(
        string="ACT Company ID",
        copy=False,
        index=True,
        help="Unique identifier from the ACT! CRM company record",
    )
    act_last_sync = fields.Datetime(
        string="Last ACT Sync",
        copy=False,
        readonly=True,
    )

    def action_open_act_import(self):
        """Open the ACT import wizard pre-filled for this partner."""
        self.ensure_one()
        search_type = "company" if self.is_company else "individual"
        default_search = self.name or ""
        return {
            "type": "ir.actions.act_window",
            "res_model": "act.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_search_type": search_type,
                "default_search_term": default_search,
                "default_partner_id": self.id,
            },
        }
