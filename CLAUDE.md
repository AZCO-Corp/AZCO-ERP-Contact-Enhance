# AZCO-ERP-Contact-Enhance

Odoo 18 module (`act_contact_import`) that integrates ACT! CRM data into Odoo partner/contact management, replaces Odoo's paid autocomplete with Google Places, and adds contact management UX improvements.

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
   - Duplicate detection: shows existing Odoo partner if ACT ID already imported, with "Go to" button

2. **Sync Wizard** (`act.sync.wizard`) — accessed from partner form "Sync with ACT" button
   - UPDATES the currently open partner record (never creates new)
   - Auto-detects company vs individual based on the open record
   - Auto-searches if partner has a name (skips search screen)
   - No partner (blank record) → searches both companies and individuals
   - Shows field-by-field diff preview (Current Odoo vs From ACT) with checkboxes
   - User picks which fields to apply before committing
   - No-results returns to search form (not an error) so user can try again
   - Duplicate detection: blocks preview for records already linked to a DIFFERENT partner, allows self-update

### Google Places Autocomplete
- Overrides `partner_autocomplete` module's `autocomplete_by_name()` to use Google Places API
- Returns full address, phone, website, location type (manufacturer, headquarters, etc.)
- `enrich_by_duns()` re-fetches place details + scrapes website meta tags for logo/description
- JS patch stops autocomplete from auto-saving — user reviews and saves manually
- Website URLs normalized from http:// to https://
- API key stored in `ir.config_parameter` key `google_places.api_key` (NOT in repo)

### Partner Form Enhancements
- **Sync with ACT** button — JS widget (not object button) so it doesn't force-save the record
- **Blacklist button** — ban icon next to email opens wizard with reason picker (uses `mail.blacklist`)
- **Clipboard paste** for images — clipboard icon on image hover, downloads URL and sets as photo
- **Company field** — editable on company records (with "All Companies (Shared)" placeholder), readonly on contacts with computed label showing inherited company or "All Companies (Shared)"
- **Parent industry** — contacts show parent company's Main Industry and Secondary Industries (readonly)
- **ACT tab** — shows ACT Contact/Company IDs and last sync timestamp

### Models:
- `res.partner` — extended with ACT fields, Google Places autocomplete, blacklist action, clipboard image download, company_id_label, parent industry related fields
- `act.import.wizard` / `.line` / `.contact` — import flow transient models
- `act.sync.wizard` / `.line` / `.diff` — sync flow transient models
- `partner.blacklist.wizard` — email blacklist with reason picker

### Key files:
- `wizards/act_import_wizard.py` — all wizard logic + `ActMixin` shared helpers
- `wizards/partner_blacklist_wizard.py` — blacklist wizard
- `views/act_import_wizard_views.xml` — both wizard form views + menu item
- `views/res_partner_views.xml` — partner form customizations
- `views/partner_blacklist_wizard_views.xml` — blacklist wizard form
- `models/res_partner.py` — field extensions, Google Places, clipboard download
- `static/src/js/partner_autocomplete_patch.js` — stops autocomplete auto-save
- `static/src/js/sync_button.js` — sync button widget (no force-save)
- `static/src/js/image_clipboard_patch.js` — clipboard paste for images
- `static/src/xml/image_field.xml` — clipboard button overlay on image widget
- `data/ir_config_parameter.xml` — connection defaults (secrets use CHANGE_ME placeholders)

## ACT Database (READ-ONLY)
- **Server:** AZCO09, Port: 14330, Instance: ACT7, DB: AZCO (IP in system params, not in repo)
- **Odoo user:** `odoo_act_reader` — SELECT only on TBL_CONTACT, TBL_COMPANY, TBL_ADDRESS, TBL_PHONE, TBL_EMAIL, TBL_COMPANY_CONTACT. DENY INSERT/UPDATE/DELETE/ALTER.
- **Connection params** stored in `ir.config_parameter` (host uses IP, not hostname, because Docker can't resolve domain names)
- **Driver:** pymssql (installed in Docker container + added to Dockerfile.odoo)
- **Data volume:** ~18,500 companies, ~47,000 contacts

## Deployment
- Odoo 18 runs on `azco26` (ssh root@azco26) in Docker at `/home/odoo18/`
- Docker DNS: `8.8.8.8` (external) + `10.0.0.117` (internal DC) in docker-compose.yml
- Module lives at `/home/odoo18/addons/act_contact_import/`
- Deploy: `scp -r act_contact_import root@azco26:/home/odoo18/addons/`
- If adding new Python models: `ssh root@azco26 "docker restart odoo18"` then upgrade via XML-RPC
- If only changing views/XML: upgrade via XML-RPC is enough (no restart needed)
- If changing JS/XML assets: upgrade via XML-RPC to rebuild assets, then Ctrl+Shift+R in browser
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
- NEVER commit secrets to the repo — use CHANGE_ME placeholders, set real values in Odoo system params
- Odoo `type="object"` buttons force a save — use JS widgets for buttons that shouldn't save
- Address fields must be written AFTER partner create (separate write), because Odoo onchanges on is_company/parent_id can blank them during create
- Company field (company_id) on contacts is readonly — inherited from parent. Use computed `company_id_label` to show "All Companies (Shared)" when blank

## Multi-Company
- Two companies: AZCO (id=2) and Securus (id=1)
- `company_id` on partner controls visibility via existing Odoo record rule
- Set on company records, cascades to contacts via onchange
- Blank = visible to all ("All Companies (Shared)")
