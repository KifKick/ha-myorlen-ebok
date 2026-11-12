// Entry point: registers the card and its editor, and lists the card in the
// dashboard card picker (with a suggestion when adding a card from a meter entity).

import { DOMAIN } from "./const";
import { MyOrlenCardEditor } from "./editors";
import type { HomeAssistant } from "./ha-types";
import { MyOrlenCard } from "./myorlen-card";

declare const __CARD_VERSION__: string; // injected by build.mjs from the integration's manifest.json

const DOCS_URL = "https://github.com/KifKick/ha-myorlen-ebok#karta";

const ELEMENTS: [string, CustomElementConstructor][] = [
  ["myorlen-ebok-card", MyOrlenCard],
  ["myorlen-ebok-card-editor", MyOrlenCardEditor],
];

// Guarded, so loading the file twice (e.g. a leftover manual resource) does not
// throw on a duplicate define().
if (!customElements.get("myorlen-ebok-card")) {
  for (const [tag, element] of ELEMENTS) customElements.define(tag, element);

  const cards = (window as any).customCards ?? ((window as any).customCards = []);
  cards.push({
    type: "myorlen-ebok-card",
    name: "myORLEN eBOK",
    description:
      "Gas bills from myORLEN eBOK: amount to pay and its state, invoices, meter reading, bill estimate, balance and eBOK notices.",
    preview: true,
    documentationURL: DOCS_URL,
    getEntitySuggestion(hass: HomeAssistant, entityId: string) {
      const entry = hass.entities?.[entityId];
      return entry?.platform === DOMAIN && entry.device_id
        ? [{ config: { type: "custom:myorlen-ebok-card", device_id: entry.device_id } }]
        : undefined;
    },
  });

  console.info(
    `%c MYORLEN-EBOK-CARD %c ${__CARD_VERSION__} `,
    "color: white; background: #d81e04; font-weight: 700;",
    "color: #d81e04; background: white; font-weight: 700;",
  );
}
