import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import pymssql
except ImportError:
    pymssql = None
    _logger.warning("pymssql not installed — ACT Contact Import will not work")


class ActImportWizard(models.TransientModel):
    _name = "act.import.wizard"
    _description = "Import Contact from ACT"

    search_term = fields.Char(string="Search", required=True)
    search_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="Search For",
        required=True,
        default="company",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Target Partner",
        help="If set, selected ACT record will populate this partner",
    )
    result_ids = fields.One2many(
        "act.import.wizard.line", "wizard_id", string="Results"
    )
    state = fields.Selection(
        [("search", "Search"), ("results", "Results")],
        default="search",
    )

    def _get_act_connection(self):
        if not pymssql:
            raise UserError(
                _("pymssql is not installed. Please install it in the Odoo environment.")
            )
        ICP = self.env["ir.config_parameter"].sudo()
        host = ICP.get_param("act_import.db_host", "AZCO09")
        port = int(ICP.get_param("act_import.db_port", "14330"))
        database = ICP.get_param("act_import.db_name", "AZCO")
        user = ICP.get_param("act_import.db_user", "odoo_act_reader")
        password = ICP.get_param("act_import.db_password", "")
        if not password:
            raise UserError(
                _(
                    "ACT database password not configured. "
                    "Go to Settings → Technical → Parameters → System Parameters "
                    "and set 'act_import.db_password'."
                )
            )
        try:
            conn = pymssql.connect(
                server=host, port=port, user=user, password=password,
                database=database, login_timeout=10,
            )
            return conn
        except Exception as e:
            raise UserError(_("Cannot connect to ACT database: %s") % str(e))

    def action_search(self):
        self.ensure_one()
        conn = self._get_act_connection()
        cursor = conn.cursor(as_dict=True)
        term = f"%{self.search_term}%"
        lines = []

        try:
            if self.search_type == "company":
                cursor.execute(
                    """
                    SELECT TOP 50
                        co.COMPANYID, co.NAME, co.INDUSTRY, co.WEBADDRESS,
                        co.NUMEMPLOYEES, co.TERRITORY, co.REGION,
                        a.LINE1, a.LINE2, a.CITY, a.STATE, a.POSTALCODE, a.COUNTRYNAME,
                        p.NUMBERDISPLAY AS phone,
                        e.ADDRESS AS email
                    FROM TBL_COMPANY co
                    OUTER APPLY (
                        SELECT TOP 1 LINE1, LINE2, CITY, STATE, POSTALCODE, COUNTRYNAME
                        FROM TBL_ADDRESS
                        WHERE COMPANYID = co.COMPANYID AND CONTACTID IS NULL
                        ORDER BY ADDRESSID
                    ) a
                    LEFT JOIN (
                        SELECT COMPANYID, MIN(NUMBERDISPLAY) AS NUMBERDISPLAY
                        FROM TBL_PHONE WHERE COMPANYID IS NOT NULL AND CONTACTID IS NULL
                        GROUP BY COMPANYID
                    ) p ON p.COMPANYID = co.COMPANYID
                    LEFT JOIN (
                        SELECT COMPANYID, MIN(ADDRESS) AS ADDRESS
                        FROM TBL_EMAIL WHERE COMPANYID IS NOT NULL AND CONTACTID IS NULL
                        GROUP BY COMPANYID
                    ) e ON e.COMPANYID = co.COMPANYID
                    WHERE co.NAME LIKE %s
                    ORDER BY co.NAME
                    """,
                    (term,),
                )
            else:
                cursor.execute(
                    """
                    SELECT TOP 50
                        c.CONTACTID, c.COMPANYID, c.FIRSTNAME, c.LASTNAME,
                        c.FULLNAME, c.JOBTITLE, c.COMPANYNAME, c.DEPARTMENT,
                        a.LINE1, a.LINE2, a.CITY, a.STATE, a.POSTALCODE, a.COUNTRYNAME,
                        p.NUMBERDISPLAY AS phone,
                        p2.NUMBERDISPLAY AS mobile,
                        e.ADDRESS AS email
                    FROM TBL_CONTACT c
                    OUTER APPLY (
                        SELECT TOP 1 LINE1, LINE2, CITY, STATE, POSTALCODE, COUNTRYNAME
                        FROM TBL_ADDRESS WHERE CONTACTID = c.CONTACTID
                        ORDER BY ADDRESSID
                    ) a
                    LEFT JOIN (
                        SELECT CONTACTID, MIN(NUMBERDISPLAY) AS NUMBERDISPLAY
                        FROM TBL_PHONE WHERE CONTACTID IS NOT NULL
                        GROUP BY CONTACTID
                    ) p ON p.CONTACTID = c.CONTACTID
                    LEFT JOIN (
                        SELECT CONTACTID, MIN(NUMBERDISPLAY) AS NUMBERDISPLAY
                        FROM TBL_PHONE WHERE CONTACTID IS NOT NULL
                        AND NUMBERDISPLAY != (
                            SELECT MIN(NUMBERDISPLAY) FROM TBL_PHONE ph2
                            WHERE ph2.CONTACTID = TBL_PHONE.CONTACTID
                        )
                        GROUP BY CONTACTID
                    ) p2 ON p2.CONTACTID = c.CONTACTID
                    LEFT JOIN (
                        SELECT CONTACTID, MIN(ADDRESS) AS ADDRESS
                        FROM TBL_EMAIL WHERE CONTACTID IS NOT NULL
                        GROUP BY CONTACTID
                    ) e ON e.CONTACTID = c.CONTACTID
                    WHERE c.FULLNAME LIKE %s OR c.COMPANYNAME LIKE %s
                    ORDER BY c.FULLNAME
                    """,
                    (term, term),
                )

            rows = cursor.fetchall()
            if not rows:
                raise UserError(
                    _("No results found in ACT for '%s'") % self.search_term
                )

            for row in rows:
                vals = {
                    "wizard_id": self.id,
                    "search_type": self.search_type,
                }
                if self.search_type == "company":
                    vals.update(
                        {
                            "act_company_id": str(row["COMPANYID"]),
                            "name": row["NAME"] or "",
                            "industry": row["INDUSTRY"] or "",
                            "website": row["WEBADDRESS"] or "",
                            "street": row["LINE1"] or "",
                            "street2": row["LINE2"] or "",
                            "city": row["CITY"] or "",
                            "state_name": row["STATE"] or "",
                            "zip": row["POSTALCODE"] or "",
                            "country_name": row["COUNTRYNAME"] or "",
                            "phone": row["phone"] or "",
                            "email": row["email"] or "",
                            "employees": row["NUMEMPLOYEES"] or 0,
                        }
                    )
                else:
                    vals.update(
                        {
                            "act_contact_id": str(row["CONTACTID"]),
                            "act_company_id": str(row["COMPANYID"] or ""),
                            "name": row["FULLNAME"] or "",
                            "function": row["JOBTITLE"] or "",
                            "company_name_act": row["COMPANYNAME"] or "",
                            "street": row["LINE1"] or "",
                            "street2": row["LINE2"] or "",
                            "city": row["CITY"] or "",
                            "state_name": row["STATE"] or "",
                            "zip": row["POSTALCODE"] or "",
                            "country_name": row["COUNTRYNAME"] or "",
                            "phone": row["phone"] or "",
                            "mobile": row["mobile"] or "",
                            "email": row["email"] or "",
                        }
                    )
                lines.append((0, 0, vals))

        finally:
            conn.close()

        self.write({"result_ids": lines, "state": "results"})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_back(self):
        self.result_ids.unlink()
        self.state = "search"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class ActImportWizardLine(models.TransientModel):
    _name = "act.import.wizard.line"
    _description = "ACT Import Result Line"

    wizard_id = fields.Many2one("act.import.wizard", ondelete="cascade")
    search_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")]
    )
    act_contact_id = fields.Char()
    act_company_id = fields.Char()
    name = fields.Char(string="Name")
    function = fields.Char(string="Job Title")
    company_name_act = fields.Char(string="Company (ACT)")
    industry = fields.Char()
    website = fields.Char()
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_name = fields.Char()
    zip = fields.Char()
    country_name = fields.Char()
    phone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()
    employees = fields.Integer()

    def action_import(self):
        """Import this ACT record into the target partner or create new."""
        self.ensure_one()
        wizard = self.wizard_id
        partner = wizard.partner_id

        # Resolve state
        state = False
        if self.state_name:
            state = self.env["res.country.state"].search(
                [
                    "|",
                    ("name", "=ilike", self.state_name),
                    ("code", "=ilike", self.state_name),
                ],
                limit=1,
            )

        # Resolve country
        country = False
        if self.country_name:
            country = self.env["res.country"].search(
                [
                    "|",
                    ("name", "=ilike", self.country_name),
                    ("code", "=ilike", self.country_name),
                ],
                limit=1,
            )
        if not country and state:
            country = state.country_id

        vals = {
            "street": self.street or False,
            "street2": self.street2 or False,
            "city": self.city or False,
            "state_id": state.id if state else False,
            "zip": self.zip or False,
            "country_id": country.id if country else False,
            "phone": self.phone or False,
            "email": self.email or False,
            "act_last_sync": fields.Datetime.now(),
        }

        if self.search_type == "company":
            vals.update(
                {
                    "name": self.name,
                    "is_company": True,
                    "website": self.website or False,
                    "act_company_id": self.act_company_id,
                }
            )
        else:
            # For individuals, try to find/link parent company
            parent = False
            if self.act_company_id:
                parent = self.env["res.partner"].search(
                    [("act_company_id", "=", self.act_company_id), ("is_company", "=", True)],
                    limit=1,
                )
            vals.update(
                {
                    "name": self.name,
                    "is_company": False,
                    "function": self.function or False,
                    "mobile": self.mobile or False,
                    "act_contact_id": self.act_contact_id,
                    "act_company_id": self.act_company_id or False,
                }
            )
            if parent:
                vals["parent_id"] = parent.id

        if partner:
            # Update existing partner — only set non-empty values
            update_vals = {k: v for k, v in vals.items() if v}
            partner.write(update_vals)
            action = {
                "type": "ir.actions.act_window",
                "res_model": "res.partner",
                "res_id": partner.id,
                "view_mode": "form",
                "target": "current",
            }
        else:
            partner = self.env["res.partner"].create(vals)
            action = {
                "type": "ir.actions.act_window",
                "res_model": "res.partner",
                "res_id": partner.id,
                "view_mode": "form",
                "target": "current",
            }

        return action
