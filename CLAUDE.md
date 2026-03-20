# AZCO-ERP-Contact-Enhance

Odoo 18 module (`act_contact_import`) that integrates ACT! CRM data into Odoo partner/contact management.

## Repo
- GitHub: https://github.com/AZCO-Corp/AZCO-ERP-Contact-Enhance
- Branch: `main`

## Architecture

### Two wizards, two distinct flows:

1. **Import Wizard** (`act.import.wizard`) — accessed from Contacts list page menu "Import from ACT"
   - Searches BOTH companies and individuals simultaneously (no type selector)
   - Creates NEW partner records
   - Companies have "View Contacts" button → checkbox bulk-import of associated people
   - Importing an individual auto-creates their parent company from ACT if not already in Odoo

2. **Sync Wizard** (`act.sync.wizard`) — accessed from partner form "Sync with ACT" button
   - UPDATES the currently open partner record (never creates new)
   - Auto-detects company vs individual based on the open record
   - Shows field-by-field diff preview (Current Odoo vs From ACT) with checkboxes
   - User picks which fields to apply before committing

### Models:
- `res.partner` — extended with `act_contact_id`, `act_company_id`, `act_last_sync` (shown in "ACT" tab)
- `act.import.wizard` / `.line` / `.contact` — import flow transient models
- `act.sync.wizard` / `.line` / `.diff` — sync flow transient models

### Key files:
- `wizards/act_import_wizard.py` — all wizard logic + `ActMixin` shared helpers
- `views/act_import_wizard_views.xml` — both wizard form views + menu item
- `views/res_partner_views.xml` — partner form button + ACT tab
- `models/res_partner.py` — field extensions + `action_open_act_sync()`
- `data/ir_config_parameter.xml` — ACT connection defaults

## ACT Database (READ-ONLY)
- **Server:** AZCO09 (CHANGE_ME), Port: 14330, Instance: ACT7, DB: AZCO
- **Odoo user:** `odoo_act_reader` — SELECT only on TBL_CONTACT, TBL_COMPANY, TBL_ADDRESS, TBL_PHONE, TBL_EMAIL, TBL_COMPANY_CONTACT. DENY INSERT/UPDATE/DELETE/ALTER.
- **Connection params** stored in `ir.config_parameter` (host uses IP, not hostname, because Docker can't resolve domain names)
- **Driver:** pymssql (installed in Docker container + added to Dockerfile.odoo)
- **Data volume:** ~18,500 companies, ~47,000 contacts

## Deployment
- Odoo 18 runs on `azco26` (ssh root@azco26) in Docker at `/home/odoo18/`
- Module lives at `/home/odoo18/addons/act_contact_import/`
- Deploy: `scp -r act_contact_import root@azco26:/home/odoo18/addons/`
- If adding new Python models: `ssh root@azco26 "docker restart odoo18"` then upgrade via XML-RPC
- If only changing views/XML: upgrade via XML-RPC is enough (no restart needed)
- Upgrade command (Python):
  ```python
  # SSL context needed (self-signed cert)
  models.execute_kw(db, uid, api_key, 'ir.module.module', 'button_immediate_upgrade', [mod_ids])
  ```
- Odoo creds at `~/.config/odoo/.env` (URL, API key, UID=2, DB=azco26)
- DB creds at `~/.config/db/.env`

## Conventions
- All ACT queries use `ActMixin` static methods for connection, geo resolution, and company import
- SQL fragments `_COMPANY_SQL` and `_CONTACT_SQL` are module-level constants reused across wizards
- Address joins use `OUTER APPLY (SELECT TOP 1 ...)` to avoid row multiplication
- Never write to ACT — the user (`odoo_act_reader`) has explicit DENY on all write operations
