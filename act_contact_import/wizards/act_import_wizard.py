import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import pymssql
except ImportError:
    pymssql = None
    _logger.warning("pymssql not installed — ACT Contact Import will not work")


# ── shared SQL fragments ──────────────────────────────────────────────

_COMPANY_SQL = """
    SELECT TOP 50
        co.COMPANYID, co.NAME, co.INDUSTRY, co.WEBADDRESS,
        co.NUMEMPLOYEES, co.TERRITORY, co.REGION,
        a.LINE1, a.LINE2, a.CITY, a.STATE, a.POSTALCODE, a.COUNTRYNAME,
        p.NUMBERDISPLAY AS phone,
        e.ADDRESS AS email,
        (SELECT COUNT(*) FROM TBL_COMPANY_CONTACT cc
         WHERE cc.COMPANYID = co.COMPANYID) AS contact_count
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
"""

_CONTACT_SQL = """
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
"""


# ── helper mixin ──────────────────────────────────────────────────────

class ActMixin:
    """Shared helpers — not a model, just mixed in."""

    @staticmethod
    def _get_act_conn(env):
        if not pymssql:
            raise UserError(
                _("pymssql is not installed. Install it in the Odoo environment.")
            )
        ICP = env["ir.config_parameter"].sudo()
        host = ICP.get_param("act_import.db_host", "AZCO09")
        port = int(ICP.get_param("act_import.db_port", "14330"))
        database = ICP.get_param("act_import.db_name", "AZCO")
        user = ICP.get_param("act_import.db_user", "odoo_act_reader")
        password = ICP.get_param("act_import.db_password", "")
        if not password:
            raise UserError(
                _(
                    "ACT database password not configured. "
                    "Set 'act_import.db_password' in System Parameters."
                )
            )
        try:
            return pymssql.connect(
                server=host, port=port, user=user, password=password,
                database=database, login_timeout=10,
            )
        except Exception as e:
            raise UserError(_("Cannot connect to ACT database: %s") % str(e))

    @staticmethod
    def _resolve_geo(env, state_name, country_name):
        state = False
        if state_name:
            state = env["res.country.state"].search(
                ["|", ("name", "=ilike", state_name), ("code", "=ilike", state_name)],
                limit=1,
            )
        country = False
        if country_name:
            country = env["res.country"].search(
                ["|", ("name", "=ilike", country_name), ("code", "=ilike", country_name)],
                limit=1,
            )
        if not country and state:
            country = state.country_id
        return state, country

    @staticmethod
    def _import_company_from_act(env, act_company_id):
        """Ensure the ACT company exists in Odoo, creating if needed."""
        if not act_company_id:
            return env["res.partner"]

        existing = env["res.partner"].search(
            [("act_company_id", "=", act_company_id), ("is_company", "=", True)],
            limit=1,
        )
        if existing:
            return existing

        conn = ActMixin._get_act_conn(env)
        cursor = conn.cursor(as_dict=True)
        try:
            cursor.execute(
                _COMPANY_SQL + " WHERE co.COMPANYID = %s",
                (act_company_id,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return env["res.partner"]

        state, country = ActMixin._resolve_geo(env, row["STATE"], row["COUNTRYNAME"])
        return env["res.partner"].create({
            "name": row["NAME"],
            "is_company": True,
            "website": row["WEBADDRESS"] or False,
            "street": row["LINE1"] or False,
            "street2": row["LINE2"] or False,
            "city": row["CITY"] or False,
            "state_id": state.id if state else False,
            "zip": row["POSTALCODE"] or False,
            "country_id": country.id if country else False,
            "phone": row["phone"] or False,
            "email": row["email"] or False,
            "act_company_id": act_company_id,
            "act_last_sync": fields.Datetime.now(),
        })


# ═════════════════════════════════════════════════════════════════════
#  IMPORT wizard  — launched from the Contacts LIST page
#  Searches BOTH companies and individuals at once. Creates NEW records.
# ═════════════════════════════════════════════════════════════════════

class ActImportWizard(models.TransientModel):
    _name = "act.import.wizard"
    _description = "Import from ACT"

    search_term = fields.Char(string="Search", required=True)
    result_ids = fields.One2many(
        "act.import.wizard.line", "wizard_id", string="Results",
    )
    contact_ids = fields.One2many(
        "act.import.wizard.contact", "wizard_id", string="Company Contacts",
    )
    company_line_id = fields.Many2one(
        "act.import.wizard.line", string="Selected Company",
    )
    state = fields.Selection(
        [("search", "Search"), ("results", "Results"), ("contacts", "Company Contacts")],
        default="search",
    )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ── search ────────────────────────────────────────────────────────

    def action_search(self):
        self.ensure_one()
        conn = ActMixin._get_act_conn(self.env)
        cursor = conn.cursor(as_dict=True)
        term = f"%{self.search_term}%"
        lines = []

        try:
            # Companies
            cursor.execute(
                _COMPANY_SQL + " WHERE co.NAME LIKE %s ORDER BY co.NAME",
                (term,),
            )
            for row in cursor.fetchall():
                lines.append((0, 0, {
                    "wizard_id": self.id,
                    "record_type": "company",
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
                    "contact_count": row["contact_count"] or 0,
                }))

            # Individuals
            cursor.execute(
                _CONTACT_SQL
                + " WHERE c.FULLNAME LIKE %s OR c.COMPANYNAME LIKE %s"
                + " ORDER BY c.FULLNAME",
                (term, term),
            )
            for row in cursor.fetchall():
                lines.append((0, 0, {
                    "wizard_id": self.id,
                    "record_type": "individual",
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
                }))

        finally:
            conn.close()

        if not lines:
            raise UserError(
                _("No results found in ACT for '%s'") % self.search_term
            )

        self.write({"result_ids": lines, "state": "results"})
        return self._reopen()

    # ── navigation ────────────────────────────────────────────────────

    def action_back(self):
        self.result_ids.unlink()
        self.contact_ids.unlink()
        self.company_line_id = False
        self.state = "search"
        return self._reopen()

    def action_back_to_results(self):
        self.contact_ids.unlink()
        self.company_line_id = False
        self.state = "results"
        return self._reopen()

    def action_import_selected_contacts(self):
        self.ensure_one()
        return self.contact_ids.action_import_selected()


class ActImportWizardLine(models.TransientModel):
    _name = "act.import.wizard.line"
    _description = "ACT Import Result Line"

    wizard_id = fields.Many2one("act.import.wizard", ondelete="cascade")
    record_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="Type",
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
    contact_count = fields.Integer(string="# Contacts")

    def action_import(self):
        """Create a new Odoo partner from this ACT result."""
        self.ensure_one()
        state, country = ActMixin._resolve_geo(
            self.env, self.state_name, self.country_name
        )

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

        if self.record_type == "company":
            vals.update({
                "name": self.name,
                "is_company": True,
                "website": self.website or False,
                "act_company_id": self.act_company_id,
            })
        else:
            parent = self.env["res.partner"]
            if self.act_company_id:
                parent = ActMixin._import_company_from_act(
                    self.env, self.act_company_id
                )
            vals.update({
                "name": self.name,
                "is_company": False,
                "function": self.function or False,
                "mobile": self.mobile or False,
                "act_contact_id": self.act_contact_id,
                "act_company_id": self.act_company_id or False,
            })
            if parent:
                vals["parent_id"] = parent.id

        partner = self.env["res.partner"].create(vals)
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": partner.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_contacts(self):
        """Load all contacts for this company from ACT."""
        self.ensure_one()
        wizard = self.wizard_id
        conn = ActMixin._get_act_conn(self.env)
        cursor = conn.cursor(as_dict=True)

        try:
            cursor.execute(
                _CONTACT_SQL
                + """
                INNER JOIN TBL_COMPANY_CONTACT cc
                    ON cc.CONTACTID = c.CONTACTID
                WHERE cc.COMPANYID = %s
                ORDER BY c.FULLNAME
                """,
                (self.act_company_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            raise UserError(_("No contacts found for this company in ACT."))

        contact_lines = []
        for row in rows:
            already = bool(self.env["res.partner"].search_count(
                [("act_contact_id", "=", str(row["CONTACTID"]))]
            ))
            contact_lines.append((0, 0, {
                "wizard_id": wizard.id,
                "selected": not already,
                "already_imported": already,
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
            }))

        wizard.write({
            "contact_ids": contact_lines,
            "company_line_id": self.id,
            "state": "contacts",
        })
        return wizard._reopen()


class ActImportWizardContact(models.TransientModel):
    _name = "act.import.wizard.contact"
    _description = "ACT Company Contact Line"

    wizard_id = fields.Many2one("act.import.wizard", ondelete="cascade")
    selected = fields.Boolean(string="Import", default=True)
    already_imported = fields.Boolean(string="Already in Odoo", readonly=True)
    act_contact_id = fields.Char()
    act_company_id = fields.Char()
    name = fields.Char(string="Name")
    function = fields.Char(string="Job Title")
    company_name_act = fields.Char(string="Company (ACT)")
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_name = fields.Char()
    zip = fields.Char()
    country_name = fields.Char()
    phone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()

    def action_import_selected(self):
        """Bulk import all selected contacts for the company."""
        wizard = self[0].wizard_id if self else self.env["act.import.wizard"]
        if not wizard:
            raise UserError(_("No wizard context found."))

        company_line = wizard.company_line_id
        if not company_line:
            raise UserError(_("No company selected."))

        parent = ActMixin._import_company_from_act(
            self.env, company_line.act_company_id
        )

        selected = self.filtered(lambda c: c.selected and not c.already_imported)
        if not selected:
            raise UserError(_("No contacts selected for import."))

        created_partners = self.env["res.partner"]
        for contact in selected:
            state, country = ActMixin._resolve_geo(
                self.env, contact.state_name, contact.country_name
            )
            partner = self.env["res.partner"].create({
                "name": contact.name,
                "is_company": False,
                "function": contact.function or False,
                "parent_id": parent.id if parent else False,
                "street": contact.street or False,
                "street2": contact.street2 or False,
                "city": contact.city or False,
                "state_id": state.id if state else False,
                "zip": contact.zip or False,
                "country_id": country.id if country else False,
                "phone": contact.phone or False,
                "mobile": contact.mobile or False,
                "email": contact.email or False,
                "act_contact_id": contact.act_contact_id,
                "act_company_id": contact.act_company_id or False,
                "act_last_sync": fields.Datetime.now(),
            })
            created_partners |= partner

        if parent:
            return {
                "type": "ir.actions.act_window",
                "res_model": "res.partner",
                "res_id": parent.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": created_partners[0].id if created_partners else False,
            "view_mode": "form",
            "target": "current",
        }


# ═════════════════════════════════════════════════════════════════════
#  SYNC wizard  — launched from an OPEN partner FORM
#  Searches ACT by the partner's existing name/type. UPDATES that record.
# ═════════════════════════════════════════════════════════════════════

class ActSyncWizard(models.TransientModel):
    _name = "act.sync.wizard"
    _description = "Sync Partner with ACT"

    partner_id = fields.Many2one("res.partner", required=True, readonly=True)
    partner_name = fields.Char(related="partner_id.name", readonly=True)
    partner_is_company = fields.Boolean(related="partner_id.is_company", readonly=True)
    search_term = fields.Char(string="Search", required=True)
    result_ids = fields.One2many(
        "act.sync.wizard.line", "wizard_id", string="Results",
    )
    state = fields.Selection(
        [("search", "Search"), ("results", "Results")],
        default="search",
    )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_search(self):
        self.ensure_one()
        conn = ActMixin._get_act_conn(self.env)
        cursor = conn.cursor(as_dict=True)
        term = f"%{self.search_term}%"
        lines = []

        try:
            if self.partner_is_company:
                cursor.execute(
                    _COMPANY_SQL + " WHERE co.NAME LIKE %s ORDER BY co.NAME",
                    (term,),
                )
                for row in cursor.fetchall():
                    lines.append((0, 0, {
                        "wizard_id": self.id,
                        "record_type": "company",
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
                    }))
            else:
                cursor.execute(
                    _CONTACT_SQL
                    + " WHERE c.FULLNAME LIKE %s OR c.COMPANYNAME LIKE %s"
                    + " ORDER BY c.FULLNAME",
                    (term, term),
                )
                for row in cursor.fetchall():
                    lines.append((0, 0, {
                        "wizard_id": self.id,
                        "record_type": "individual",
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
                    }))
        finally:
            conn.close()

        if not lines:
            raise UserError(
                _("No results found in ACT for '%s'") % self.search_term
            )

        self.write({"result_ids": lines, "state": "results"})
        return self._reopen()

    def action_back(self):
        self.result_ids.unlink()
        self.state = "search"
        return self._reopen()


class ActSyncWizardLine(models.TransientModel):
    _name = "act.sync.wizard.line"
    _description = "ACT Sync Result Line"

    wizard_id = fields.Many2one("act.sync.wizard", ondelete="cascade")
    record_type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="Type",
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

    def action_sync(self):
        """Update the open partner record with data from this ACT result."""
        self.ensure_one()
        partner = self.wizard_id.partner_id
        state, country = ActMixin._resolve_geo(
            self.env, self.state_name, self.country_name
        )

        vals = {
            "act_last_sync": fields.Datetime.now(),
        }

        # Only update fields that have data from ACT
        if self.street:
            vals["street"] = self.street
        if self.street2:
            vals["street2"] = self.street2
        if self.city:
            vals["city"] = self.city
        if state:
            vals["state_id"] = state.id
        if self.zip:
            vals["zip"] = self.zip
        if country:
            vals["country_id"] = country.id
        if self.phone:
            vals["phone"] = self.phone
        if self.email:
            vals["email"] = self.email

        if self.record_type == "company":
            vals["act_company_id"] = self.act_company_id
            if self.website:
                vals["website"] = self.website
        else:
            vals["act_contact_id"] = self.act_contact_id
            if self.act_company_id:
                vals["act_company_id"] = self.act_company_id
                # Auto-import parent company if needed
                parent = ActMixin._import_company_from_act(
                    self.env, self.act_company_id
                )
                if parent:
                    vals["parent_id"] = parent.id
            if self.function:
                vals["function"] = self.function
            if self.mobile:
                vals["mobile"] = self.mobile

        partner.write(vals)

        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": partner.id,
            "view_mode": "form",
            "target": "current",
        }
