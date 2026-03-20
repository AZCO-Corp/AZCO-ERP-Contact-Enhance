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

    def action_open_act_sync(self):
        """Open the ACT sync wizard to update this partner from ACT."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "act.sync.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.id,
                "default_search_term": self.name or "",
            },
        }
