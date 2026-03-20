{
    "name": "ACT Contact Import",
    "version": "18.0.1.0.0",
    "category": "Contacts",
    "summary": "Import contacts and companies from ACT! CRM database",
    "description": """
Import contacts and companies from the ACT! CRM (SQL Server) database
directly into Odoo partner records.

Features:
- Search ACT database for companies and individuals
- Auto-populate partner fields from ACT data
- Read-only ACT access (no writes to ACT)
- Import from partner form via button or wizard
    """,
    "author": "AZCO Corp",
    "website": "https://github.com/AZCO-Corp/AZCO-ERP-Contact-Enhance",
    "license": "LGPL-3",
    "depends": ["contacts", "base"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/act_import_wizard_views.xml",
        "views/res_partner_views.xml",
    ],
    "external_dependencies": {
        "python": ["pymssql"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
