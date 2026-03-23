/** @odoo-module **/

import { PartnerAutoCompleteCharField } from "@partner_autocomplete/js/partner_autocomplete_fieldchar";
import { patch } from "@web/core/utils/patch";

patch(PartnerAutoCompleteCharField.prototype, {
    /**
     * Override onSelect to NOT auto-save the record.
     * The user should review the populated fields and click Save themselves.
     */
    async onSelect(option) {
        let data = await this.partnerAutocomplete.getCreateData(Object.getPrototypeOf(option));
        if (!data?.company) {
            return;
        }

        if (data.logo) {
            const logoField = this.props.record.resModel === 'res.partner' ? 'image_1920' : 'logo';
            data.company[logoField] = data.logo;
        }

        // Format the many2one fields
        const many2oneFields = ['country_id', 'state_id', 'industry_id'];
        many2oneFields.forEach((field) => {
            if (data.company[field]) {
                data.company[field] = [data.company[field].id, data.company[field].display_name];
            }
        });

        // Remove fields not on the model
        data.company = this.partnerAutocomplete.removeUselessFields(
            data.company, Object.keys(this.props.record.fields)
        );

        // Update form fields in-memory (makes them dirty, does NOT save)
        if (data.company.name) {
            await this.props.record.update({name: data.company.name});
        }
        await this.props.record.update(data.company);

        // Intentionally NOT calling this.props.record.save()
        // User reviews the fields and saves manually via the Save button.
    }
});
