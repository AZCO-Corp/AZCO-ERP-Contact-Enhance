/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, xml } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * "Sync with ACT" button widget that opens the sync wizard
 * WITHOUT saving the current record first.
 */
class SyncWithActButton extends Component {
    static template = xml`
        <button class="btn btn-secondary" t-on-click="onClick">
            <i class="fa fa-refresh me-1"/>Sync with ACT
        </button>
    `;
    static props = { ...standardWidgetProps };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onClick() {
        const record = this.props.record;
        const partnerId = record.resId;
        const partnerName = record.data.name || "";

        if (!partnerId || record.isNew) {
            // Unsaved new record — just open empty search
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "act.sync.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_partner_id: partnerId || false,
                    default_search_term: partnerName,
                },
            });
            return;
        }

        // Existing saved record — call the server method which may auto-search
        const result = await this.orm.call(
            "res.partner",
            "action_open_act_sync",
            [partnerId],
        );
        this.action.doAction(result);
    }
}

registry.category("view_widgets").add("sync_with_act_button", {
    component: SyncWithActButton,
});
