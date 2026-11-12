// Contract with the integration: the card finds entities by translation_key
// (see sensor.py and the other platforms), never by entity_id, so it works
// whatever the meter number, the user's own entity ids or the UI language.

export const DOMAIN = "myorlen_ebok";

/** Entity keys are `<platform>.<translation_key>`. */
export const ENTITY = {
  reading: "sensor.reading",
  readingDate: "sensor.reading_date",
  toPay: "sensor.to_pay",
  dueDate: "sensor.due_date",
  lastInvoice: "sensor.last_invoice",
  costPerM3: "sensor.cost_per_m3",
  balance: "sensor.balance",
  lastPayment: "sensor.last_payment",
  billEstimate: "sensor.bill_estimate",
  overdue: "binary_sensor.overdue",
  invoices: "calendar.invoices",
  notices: "event.notices",
  refresh: "button.refresh",
} as const;

/** The integration's action that submits a meter reading. */
export const ADD_READING_SERVICE = "add_reading";
/** Above this increase over the last reading the action wants an explicit confirmation. */
export const MAX_READING_INCREASE_M3 = 500;

/** Mushroom's named palette plus ORLEN's red; used as `var(--rgb-<name>)`. */
export const COLORS = [
  "orlen",
  "red",
  "pink",
  "purple",
  "deep-purple",
  "indigo",
  "blue",
  "light-blue",
  "cyan",
  "teal",
  "green",
  "light-green",
  "lime",
  "yellow",
  "amber",
  "orange",
  "deep-orange",
  "brown",
  "grey",
  "blue-grey",
] as const;
export type Color = (typeof COLORS)[number] | "disabled" | "accent";

/** Everything the card can show under its header, in the order the user picks. */
export const CARD_SECTIONS = ["alerts", "payment", "invoices", "usage", "account", "stats"] as const;
export type CardSection = (typeof CARD_SECTIONS)[number];
export const DEFAULT_SECTIONS: CardSection[] = ["alerts", "payment", "invoices", "usage", "stats"];

/** Banners for things worth knowing now. */
export const ALERT_TYPES = ["unavailable", "overdue", "due_soon", "awaiting_booking", "notice"] as const;
export type AlertType = (typeof ALERT_TYPES)[number];

/** What the header's second line shows. */
export const HEADER_INFO = ["summary", "reading", "balance", "none"] as const;
export type HeaderInfo = (typeof HEADER_INFO)[number];

export interface StatDef {
  /** Entity the chip opens. */
  entity: string;
  icon: string;
  color: Color;
}

export const STATS: Record<string, StatDef> = {
  to_pay: { entity: ENTITY.toPay, icon: "mdi:cash-clock", color: "accent" },
  due: { entity: ENTITY.dueDate, icon: "mdi:calendar-clock-outline", color: "deep-orange" },
  reading: { entity: ENTITY.reading, icon: "mdi:meter-gas-outline", color: "blue" },
  estimate: { entity: ENTITY.billEstimate, icon: "mdi:calculator-variant-outline", color: "purple" },
  cost: { entity: ENTITY.costPerM3, icon: "mdi:fire", color: "orange" },
  balance: { entity: ENTITY.balance, icon: "mdi:scale-balance", color: "teal" },
  last_payment: { entity: ENTITY.lastPayment, icon: "mdi:cash-check", color: "green" },
};
export const DEFAULT_STATS = ["to_pay", "reading", "estimate", "last_payment"];

/** Payment state of an invoice, as the integration names it. */
export type InvoiceState = "unpaid" | "awaiting_booking" | "paid";
