// Stand-ins for HA's ha-card / ha-icon (rendering real MDI paths) and a fake
// `hass` with realistic myORLEN eBOK data, so the built bundle renders as in HA.
// Everything here is made up: no real account, meter or invoice.
import * as mdi from "@mdi/js";

const toKey = (icon) =>
  "mdi" + String(icon || "").replace(/^mdi:/, "").split("-").map((p) => p[0].toUpperCase() + p.slice(1)).join("");

customElements.define(
  "ha-icon",
  class extends HTMLElement {
    static observedAttributes = ["icon"];
    set icon(v) { this._icon = v; this._render(); }
    get icon() { return this._icon; }
    attributeChangedCallback(_n, _o, v) { this.icon = v; }
    connectedCallback() { this._render(); }
    _render() {
      const path = mdi[toKey(this._icon)] ?? "";
      if (!path && this._icon) console.warn("missing icon", this._icon);
      (this.shadowRoot ?? this.attachShadow({ mode: "open" })).innerHTML = `<svg viewBox="0 0 24 24" style="width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px);fill:currentColor;display:block"><path d="${path}"/></svg>`;
    }
  },
);

customElements.define(
  "ha-card",
  class extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" }).innerHTML = `<style>:host{display:block;position:relative;background:var(--card-background-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);color:var(--primary-text-color)}</style><slot></slot>`;
    }
  },
);

const D = 86_400_000;
const day = (offset) => new Date(Date.now() + offset * D).toISOString().slice(0, 10);
const iso = (offset) => new Date(Date.now() + offset * D).toISOString();

const recent = (state) => [
  { number: "P/10000001/0010/26", due_date: day(4), gross_amount: 27.4, state },
  { number: "P/10000001/0009/26", due_date: day(-27), gross_amount: 27.4, state: "paid" },
  { number: "P/10000001/0008/26", due_date: day(-57), gross_amount: 19.73, state: "paid" },
  { number: "P/10000001/0007/26", due_date: day(-94), gross_amount: 16.06, state: "paid" },
  { number: "P/10000001/0006/26", due_date: day(-120), gross_amount: 16.06, state: "paid" },
];

/** scenario: awaiting | to_pay | overdue | paid */
export const makeHass = ({ language = "pl", dark = false, scenario = "awaiting", offline = false, notice = true, fail = false } = {}) => {
  const set = (platform, key, state, attributes = {}) => [
    platform,
    key,
    { state: offline ? "unavailable" : String(state), attributes: offline ? {} : attributes },
  ];
  const toPay = scenario === "to_pay" || scenario === "overdue" ? 27.4 : 0;
  const invoiceState = { awaiting: "awaiting_booking", to_pay: "unpaid", overdue: "unpaid", paid: "paid" }[scenario];
  const due = scenario === "overdue" ? day(-3) : day(4);
  const lastInvoice = {
    number: "P/10000001/0010/26",
    issue_date: day(-10),
    due_date: due,
    period_start: day(-42),
    period_end: day(-12),
    gross_amount: 27.4,
    to_pay: scenario === "paid" ? 0 : 27.4,
    usage_m3: 3,
    usage_kwh: 34,
    state: invoiceState,
    status: scenario === "awaiting" ? "Paid" : scenario === "paid" ? "Posted" : "",
    paid_at: scenario === "awaiting" || scenario === "paid" ? iso(-2) : null,
    automatic_payment_date: scenario === "paid" ? null : day(scenario === "overdue" ? -4 : 3),
    recent: recent(invoiceState).map((r, i) => (i === 0 ? { ...r, due_date: due } : r)),
  };
  const entries = [
    set("sensor", "reading", 56, { reading_date: iso(-12), usage: 3, reading_type: "Receiver", tariff: "W-1.12T" }),
    set("sensor", "reading_date", iso(-12)),
    set("sensor", "to_pay", toPay, {
      invoices: toPay ? ["P/10000001/0010/26"] : [],
      awaiting_booking: scenario === "awaiting" ? 27.4 : 0,
    }),
    set("sensor", "due_date", toPay ? due : "unknown", toPay ? lastInvoice : {}),
    set("sensor", "last_invoice", 27.4, lastInvoice),
    set("sensor", "cost_per_m3", 9.13),
    set("sensor", "balance", 0, { agreement: "RW/UKPG/0001/2025", agreement_start: "2025-03-11", tariff: "W-1.12T" }),
    set("sensor", "last_payment", 27.4, {
      date: day(-36),
      recent: [{ date: day(-36), amount: 27.4 }, { date: day(-66), amount: 19.73 }],
    }),
    set("sensor", "bill_estimate", 19.73, {
      net: 16.04,
      reading: 56,
      parts: [
        { description: "Dystrybucyjna zmienna", kwh: 11, gross: 1.0 },
        { description: "Paliwo gazowe", kwh: 11, gross: 2.67 },
        { description: "Opłata abonamentowa", kwh: 0, gross: 7.98 },
        { description: "Dystrybucyjna stała", kwh: 0, gross: 8.08 },
      ],
    }),
    set("binary_sensor", "overdue", scenario === "overdue" ? "on" : "off", {
      amount: scenario === "overdue" ? 27.4 : 0,
      invoices: scenario === "overdue" ? ["P/10000001/0010/26"] : [],
      since: scenario === "overdue" ? due : null,
    }),
    set("calendar", "invoices", "off"),
    set(
      "event",
      "notices",
      notice ? iso(-1) : "unknown",
      notice
        ? {
            event_type: "notice",
            title: "Prace serwisowe",
            message: "W nocy z soboty na niedzielę eBOK może działać z przerwami.",
          }
        : {},
    ),
    set("button", "refresh", "unknown"),
  ];
  const states = {};
  const entities = {};
  for (const [platform, tk, value] of entries) {
    const entityId = `${platform}.myorlen_1000001_${tk}`;
    entities[entityId] = { entity_id: entityId, device_id: "meter1", platform: "myorlen_ebok", translation_key: tk };
    states[entityId] = { entity_id: entityId, last_changed: iso(0), last_updated: iso(0), ...value };
  }
  return {
    language,
    locale: { language, number_format: "language", time_zone: "local" },
    config: { time_zone: "Europe/Warsaw" },
    themes: { darkMode: dark },
    devices: {
      meter1: {
        id: "meter1",
        name: "Gaz 8018000000000000000001",
        name_by_user: null,
        identifiers: [["myorlen_ebok", "8018000000000000000001"]],
        config_entries: ["entry1"],
        configuration_url: "https://ebok.myorlen.pl/home",
      },
    },
    entities,
    states,
    async callService(domain, service, data) {
      console.log("callService", domain, service, JSON.stringify(data));
      await new Promise((resolve) => setTimeout(resolve, 50));
      if (fail) throw new Error("Odczyt za ten okres został już podany");
      return { response: { value: data.value, can_be_cancelled: true } };
    },
    async callWS() {
      return null;
    },
  };
};
