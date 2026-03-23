/** @odoo-module **/

import { ImageField } from "@web/views/fields/image/image_field";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(ImageField.prototype, {
    setup() {
        super.setup(...arguments);
        this.rpc = useService("rpc");
    },

    async onClipboardPaste() {
        let clipText;
        try {
            clipText = await navigator.clipboard.readText();
        } catch (e) {
            this.notification.add(
                "Cannot access clipboard. Please allow clipboard permissions.",
                { type: "warning" },
            );
            return;
        }

        if (!clipText || !clipText.trim()) {
            this.notification.add("Clipboard is empty.", { type: "warning" });
            return;
        }

        clipText = clipText.trim();

        // Validate it looks like a URL
        if (!clipText.match(/^https?:\/\/.+/i)) {
            this.notification.add(
                "Clipboard does not contain a valid image URL. Copy an image URL starting with http:// or https://",
                { type: "warning" },
            );
            return;
        }

        // Call server to download the image
        try {
            const result = await this.orm.call(
                "res.partner",
                "download_image_from_url",
                [clipText],
            );
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
                return;
            }
            this.state.isValid = true;
            await this.props.record.update({ [this.props.name]: result.data });
            this.notification.add("Image set from clipboard URL.", { type: "success" });
        } catch (e) {
            this.notification.add(
                "Failed to download image from URL.",
                { type: "danger" },
            );
        }
    },
});
