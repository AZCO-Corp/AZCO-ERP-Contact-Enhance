import base64
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.types,"
    "places.nationalPhoneNumber,places.websiteUri,places.addressComponents,"
    "places.primaryTypeDisplayName"
)

# Map Google address component types → Odoo field fragments
_COMPONENT_MAP = {
    "street_number": "street_number",
    "route": "route",
    "locality": "city",
    "administrative_area_level_1": "state",
    "country": "country",
    "postal_code": "zip",
    "subpremise": "subpremise",
}


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

    # Inherited from parent company (read-only on contacts)
    parent_industry_id = fields.Many2one(
        related="parent_id.industry_id",
        string="Main Industry",
        readonly=True,
    )
    parent_secondary_industry_ids = fields.Many2many(
        related="parent_id.secondary_industry_ids",
        string="Secondary Industries",
        readonly=True,
    )
    company_id_display = fields.Char(
        string="Visibility",
        compute="_compute_company_id_display",
    )

    @api.depends("company_id")
    def _compute_company_id_display(self):
        for partner in self:
            if partner.company_id:
                partner.company_id_display = partner.company_id.name
            else:
                partner.company_id_display = "All Companies (Shared)"

    def action_open_act_sync(self):
        """Open the ACT sync wizard. Auto-searches if partner has a name."""
        self.ensure_one()
        wizard = self.env["act.sync.wizard"].create({
            "partner_id": self.id,
            "search_term": self.name or "",
        })
        # Auto-search if there's a name to search for
        if self.name and self.name.strip():
            return wizard.action_search()
        return wizard._reopen()

    # ── blacklist ──────────────────────────────────────────────────

    def action_blacklist_email(self):
        """Open a wizard to blacklist this partner's email with a reason."""
        self.ensure_one()
        if not self.email:
            from odoo.exceptions import UserError
            raise UserError("This contact has no email address to blacklist.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "partner.blacklist.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.id,
                "default_email": self.email,
            },
        }

    # ── helpers ────────────────────────────────────────────────────

    @api.model
    def _normalize_url(self, url):
        """Upgrade http:// to https:// — almost all sites support it now."""
        if url and url.startswith("http://"):
            return "https://" + url[7:]
        return url

    # ── clipboard image download ────────────────────────────────────

    @api.model
    def download_image_from_url(self, url):
        """Download an image from a URL and return base64 data."""
        if not url or not url.startswith(("http://", "https://")):
            return {"error": "Invalid URL."}
        try:
            resp = requests.get(
                url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; OdooBot)"},
                allow_redirects=True,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            return {"error": "Could not connect to the URL."}
        except requests.exceptions.Timeout:
            return {"error": "Request timed out."}
        except requests.exceptions.HTTPError as e:
            return {"error": "HTTP error: %s" % e.response.status_code}
        except Exception:
            return {"error": "Failed to download image."}

        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return {"error": "URL does not point to an image (got %s)." % content_type}

        if len(resp.content) > 10_000_000:
            return {"error": "Image is too large (max 10MB)."}

        return {"data": base64.b64encode(resp.content).decode()}

    # ── Google Places autocomplete (replaces Odoo IAP) ────────────

    @api.model
    def _get_google_api_key(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("google_places.api_key", "")
        )

    @api.model
    def autocomplete_by_name(self, query, query_country_id, timeout=15):
        """Override partner_autocomplete to use Google Places API."""
        api_key = self._get_google_api_key()
        if not api_key:
            # Fall back to original if no Google key configured
            return super().autocomplete_by_name(query, query_country_id, timeout)

        try:
            resp = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": _PLACES_FIELD_MASK,
                },
                json={
                    "textQuery": query,
                    "languageCode": "en",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
        except Exception:
            _logger.warning("Google Places API call failed", exc_info=True)
            return []

        results = []
        for place in resp.json().get("places", [])[:10]:
            result = self._format_google_place(place)
            if result:
                results.append(result)
        return results

    @api.model
    def enrich_by_duns(self, duns, timeout=15):
        """Override enrichment — re-fetch full place data + scrape website.

        The JS widget replaces the original suggestion with enrichment data,
        so we must return ALL fields (name, street, etc.) not just the extras.
        """
        # duns is actually the Google Place ID we stored
        if not duns or not str(duns).startswith("ChI"):
            return super().enrich_by_duns(duns, timeout)

        api_key = self._get_google_api_key()
        if not api_key:
            return {}

        # Re-fetch full place details (detail endpoint uses unprefixed field names)
        detail_mask = (
            "id,displayName,formattedAddress,types,"
            "nationalPhoneNumber,websiteUri,addressComponents,"
            "primaryTypeDisplayName"
        )
        try:
            resp = requests.get(
                f"https://places.googleapis.com/v1/places/{duns}",
                headers={
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": detail_mask,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            place = resp.json()
        except Exception:
            _logger.warning("Google Places detail fetch failed", exc_info=True)
            return {}

        # Format full place data (same as autocomplete results)
        result = self._format_google_place(place) or {}

        # Scrape website meta for logo + description
        website = place.get("websiteUri", "")
        if website:
            meta = self._scrape_website_meta(website, timeout)
            result.update(meta)

        return result

    @api.model
    def _format_google_place(self, place):
        """Convert a Google Places result into Odoo autocomplete format."""
        name = place.get("displayName", {}).get("text", "")
        if not name:
            return None

        # Parse address components
        components = {}
        for comp in place.get("addressComponents", []):
            for t in comp.get("types", []):
                if t in _COMPONENT_MAP:
                    key = _COMPONENT_MAP[t]
                    components[key] = comp.get("shortText") or comp.get("longText", "")
                    if key in ("state", "country"):
                        components[key + "_long"] = comp.get("longText", "")

        # Build street from components
        street_number = components.get("street_number", "")
        route = components.get("route", "")
        subpremise = components.get("subpremise", "")
        street = f"{street_number} {route}".strip()
        street2 = f"#{subpremise}" if subpremise else ""

        # Resolve country
        country = None
        country_code = components.get("country", "")
        if country_code:
            country = self.env["res.country"].search(
                [("code", "=ilike", country_code)], limit=1
            )

        # Resolve state
        state = None
        state_code = components.get("state", "")
        state_long = components.get("state_long", "")
        if country and state_code:
            state = self.env["res.country.state"].search(
                [("country_id", "=", country.id), ("code", "=ilike", state_code)],
                limit=1,
            )
        if not state and country and state_long:
            state = self.env["res.country.state"].search(
                [("country_id", "=", country.id), ("name", "=ilike", state_long)],
                limit=1,
            )

        # Build type label for description
        ptype = place.get("primaryTypeDisplayName", {}).get("text", "")

        result = {
            "name": name,
            "street": street,
            "street2": street2 or False,
            "city": components.get("city", ""),
            "zip": components.get("zip", ""),
            "phone": place.get("nationalPhoneNumber", ""),
            "website": self._normalize_url(place.get("websiteUri", "")),
            # Store Google Place ID in duns field so enrichment can use it
            "duns": place.get("id", ""),
            "is_company": True,
        }

        if country:
            result["country_id"] = {
                "id": country.id,
                "display_name": country.display_name,
            }
        if state:
            result["state_id"] = {
                "id": state.id,
                "display_name": state.display_name,
            }

        # Add type to description (shown in dropdown)
        if ptype:
            result["description"] = ptype

        return result

    @api.model
    def _scrape_website_meta(self, url, timeout=10):
        """Scrape meta tags from a website for company enrichment."""
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; OdooBot)"},
                allow_redirects=True,
            )
            resp.raise_for_status()
        except Exception:
            _logger.debug("Failed to scrape %s", url, exc_info=True)
            return {}

        result = {}
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text[:100000], "html.parser")

            # Description
            for tag in soup.find_all("meta"):
                prop = tag.get("property", "") or tag.get("name", "")
                content = tag.get("content", "")
                if prop.lower() in ("og:description", "description") and content:
                    result["additional_info"] = content[:250]
                    break

            # Logo from og:image
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                img_url = og_img["content"]
                try:
                    img_resp = requests.get(
                        img_url, timeout=5,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; OdooBot)"},
                    )
                    if img_resp.ok and len(img_resp.content) < 500_000:
                        result["logo"] = base64.b64encode(img_resp.content).decode()
                except Exception:
                    pass

        except ImportError:
            _logger.debug("BeautifulSoup not available for meta scraping")

        return result
