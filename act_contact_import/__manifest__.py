{
    "name": "ACT Contact Import",
    "version": "18.0.1.0.0",
    "category": "Contacts",
    "summary": "Import contacts and companies from ACT! CRM + Google Places autocomplete",
    "description": """
Import contacts and companies from the ACT! CRM (SQL Server) database
directly into Odoo partner records. Also replaces Odoo's paid IAP
autocomplete with free Google Places API + website meta-tag scraping.

Features:
- Search ACT database for companies and individuals
- Auto-populate partner fields from ACT data
- Read-only ACT access (no writes to ACT)
- Google Places company autocomplete (replaces Odoo IAP)
- Website meta-tag scraping for logo and description
    """,
    "author": "AZCO Corp",
    "website": "https://github.com/AZCO-Corp/AZCO-ERP-Contact-Enhance",
    "license": "LGPL-3",
    "depends": ["contacts", "base", "partner_autocomplete"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/act_import_wizard_views.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "act_contact_import/static/src/js/partner_autocomplete_patch.js",
            "act_contact_import/static/src/js/sync_button.js",
            "act_contact_import/static/src/js/image_clipboard_patch.js",
            "act_contact_import/static/src/xml/image_field.xml",
        ],
    },
    "external_dependencies": {
        "python": ["pymssql"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
