// Pure logic over the integration's states and attributes: the payment state,
// the alerts, lists from attributes, the reading form. No Lit, so it is tested
// on its own (logic.test.ts).

import type { AlertOptions } from "./config";
import { type AlertType, type InvoiceState, MAX_READING_INCREASE_M3 } from "./const";
import type { HassEntity } from "./ha-types";

/** A finite number from a state or attribute, else undefined. */
export const num = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return undefined;
  const n = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  return Number.isFinite(n) ? n : undefined;
};

const str = (value: unknown): string | undefined =>
  typeof value === "string" && value && value !== "unknown" && value !== "unavailable" ? value : undefined;

const list = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value) ? value.filter((v): v is Record<string, unknown> => typeof v === "object" && v !== null) : [];

/** The state when the entity has one, else undefined. */
export const stateOf = (stateObj?: HassEntity): string | undefined => str(stateObj?.state);

// --- Payment ------------------------------------------------------------------------

export type PaymentKind = "overdue" | "to_pay" | "awaiting" | "paid" | "unknown";

export interface Payment {
  kind: PaymentKind;
  /** The amount the state is about: to pay, overdue, awaiting booking, or the paid invoice. */
  amount?: number;
  /** Due date (overdue: since when). */
  due?: string;
  invoice?: string;
  /** When eBOK collects the payment itself. */
  automatic?: string;
  /** When the invoice was paid in eBOK. */
  paidAt?: string;
}

export interface PaymentInput {
  toPay?: HassEntity;
  dueDate?: HassEntity;
  lastInvoice?: HassEntity;
  overdue?: HassEntity;
}

/** Where the meter's bills stand, most urgent first. */
export const computePayment = ({ toPay, dueDate, lastInvoice, overdue }: PaymentInput): Payment => {
  const amount = num(stateOf(toPay));
  if (amount === undefined) return { kind: "unknown" };
  const last = lastInvoice?.attributes ?? {};
  const dueAttrs = dueDate?.attributes ?? {};

  if (overdue?.state === "on") {
    const invoices: unknown = overdue.attributes?.invoices;
    return {
      kind: "overdue",
      amount: num(overdue.attributes?.amount) ?? amount,
      due: str(overdue.attributes?.since),
      invoice: Array.isArray(invoices) ? str(invoices[0]) : undefined,
    };
  }
  if (amount > 0) {
    return {
      kind: "to_pay",
      amount,
      due: stateOf(dueDate),
      invoice: str(dueAttrs.number),
      automatic: str(dueAttrs.automatic_payment_date),
    };
  }
  const awaiting = num(toPay?.attributes?.awaiting_booking) ?? 0;
  if (awaiting > 0) {
    const lastAwaiting = last.state === "awaiting_booking";
    return {
      kind: "awaiting",
      amount: awaiting,
      due: lastAwaiting ? str(last.due_date) : undefined,
      invoice: lastAwaiting ? str(last.number) : undefined,
      automatic: lastAwaiting ? str(last.automatic_payment_date) : undefined,
      paidAt: lastAwaiting ? str(last.paid_at) : undefined,
    };
  }
  return {
    kind: "paid",
    amount: num(last.gross_amount),
    due: str(last.due_date),
    invoice: str(last.number),
    paidAt: str(last.paid_at),
  };
};

// --- Invoices, payments, estimate ---------------------------------------------------

export interface InvoiceRow {
  number: string;
  due?: string;
  amount?: number;
  state: InvoiceState;
}

const STATES: InvoiceState[] = ["unpaid", "awaiting_booking", "paid"];

export const parseInvoices = (lastInvoice?: HassEntity): InvoiceRow[] =>
  list(lastInvoice?.attributes?.recent).map((raw) => ({
    number: String(raw.number ?? ""),
    due: str(raw.due_date),
    amount: num(raw.gross_amount),
    state: STATES.includes(raw.state as InvoiceState) ? (raw.state as InvoiceState) : "unpaid",
  }));

export interface PaymentRow {
  date?: string;
  amount?: number;
}

export const parsePayments = (lastPayment?: HassEntity): PaymentRow[] =>
  list(lastPayment?.attributes?.recent).map((raw) => ({ date: str(raw.date), amount: num(raw.amount) }));

export interface EstimatePart {
  description: string;
  gross?: number;
  kwh?: number;
}

export const parseEstimateParts = (estimate?: HassEntity): EstimatePart[] =>
  list(estimate?.attributes?.parts).map((raw) => ({
    description: String(raw.description ?? ""),
    gross: num(raw.gross),
    kwh: num(raw.kwh),
  }));

// --- Notices ------------------------------------------------------------------------

export interface Notice {
  title: string;
  message: string;
  /** When eBOK published it, or when HA first saw it. */
  date?: string;
}

/** The latest notice the event entity fired, if any. */
export const parseNotice = (event?: HassEntity): Notice | undefined => {
  const attrs = event?.attributes ?? {};
  const title = str(attrs.title);
  if (!title || !stateOf(event)) return undefined;
  return { title, message: str(attrs.message) ?? "", date: str(attrs.date) ?? stateOf(event) };
};

// --- Alerts -------------------------------------------------------------------------

export interface Alert {
  type: AlertType;
  /** Days until the due date (due_soon) or since the notice (notice). */
  days?: number;
}

export interface AlertInput {
  offline: boolean;
  payment: Payment;
  notice?: Notice;
}

/** Banners in order of urgency, filtered by the configured types. */
export const computeAlerts = (
  input: AlertInput,
  options: AlertOptions,
  daysUntil: (value?: string) => number | undefined,
): Alert[] => {
  const alerts: Alert[] = [];
  if (input.offline) {
    alerts.push({ type: "unavailable" });
  } else {
    const { payment } = input;
    if (payment.kind === "overdue") alerts.push({ type: "overdue" });
    if (payment.kind === "to_pay") {
      const days = daysUntil(payment.due);
      if (days !== undefined && days >= 0 && days <= options.due_days) alerts.push({ type: "due_soon", days });
    }
    if (payment.kind === "awaiting") alerts.push({ type: "awaiting_booking" });
    if (input.notice) {
      const since = daysUntil(input.notice.date);
      if (since !== undefined && -since <= options.notice_days) alerts.push({ type: "notice", days: -since });
    }
  }
  return alerts.filter((alert) => options.types.includes(alert.type));
};

// --- Meter reading form -------------------------------------------------------------

export type ReadingCheck =
  | { ok: false; reason: "empty" | "invalid" }
  | { ok: true; value: number; lower: boolean; large: boolean };

/** A typed reading ("57", "57,5") against the last one. */
export const checkReading = (text: string, last?: number): ReadingCheck => {
  const trimmed = text.trim();
  if (!trimmed) return { ok: false, reason: "empty" };
  if (!/^\d+([.,]\d{1,3})?$/.test(trimmed)) return { ok: false, reason: "invalid" };
  const value = Number(trimmed.replace(",", "."));
  return {
    ok: true,
    value,
    lower: last !== undefined && value < last,
    large: last !== undefined && value - last > MAX_READING_INCREASE_M3,
  };
};
