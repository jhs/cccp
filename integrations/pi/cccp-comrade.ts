/**
 * cccp-comrade.ts — Pi extension: makes a Pi session a CCCP comrade.
 *
 * Placeholder while the real extension lands. Confirms the package plumbing (pi manifest, extension
 * discovery, ad hoc `pi -e` loading) end to end without touching cccp yet.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.hasUI) ctx.ui.notify("CCCP comrade placeholder active", "info");
	});
}
