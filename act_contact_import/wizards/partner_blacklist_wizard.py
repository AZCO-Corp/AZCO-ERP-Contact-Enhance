from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError


class PartnerBlacklistWizard(models.TransientModel):
    _name = "partner.blacklist.wizard"
    _description = "Blacklist Partner Email"

    partner_id = fields.Many2one("res.partner", required=True, readonly=True)
    email = fields.Char(required=True, readonly=True)
    reason_id = fields.Many2one(
        "mailing.subscription.optout",
        string="Reason",
        required=True,
    )
    note = fields.Text(string="Notes", help="Additional context for the blacklist")

    def action_blacklist(self):
        self.ensure_one()
        normalized = tools.email_normalize(self.email)
        if not normalized:
            raise UserError(_("Invalid email address."))

        # Add to blacklist
        bl_record = self.env["mail.blacklist"]._add(
            self.email,
            message=_("Manually blacklisted by %s. Reason: %s%s")
            % (
                self.env.user.name,
                self.reason_id.name,
                (" — " + self.note) if self.note else "",
            ),
        )

        # Set opt-out reason
        if bl_record and self.reason_id:
            bl_record.write({"opt_out_reason_id": self.reason_id.id})

        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "target": "current",
        }
