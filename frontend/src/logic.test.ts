import { describe, expect, it } from "vitest";

import { CARD_DEFAULTS, withDefaults } from "./config";
import { pruneConfig } from "./editors";
import { daysUntil, formatDate, formatMoney, parseDate } from "./format";
import type { HassEntity, HomeAssistant } from "./ha-types";
import { checkReading, computeAlerts, computePayment, parseEstimateParts, parseInvoices, parseNotice } from "./model";

const entity = (state: string, attributes: Record<string, unknown> = {}): HassEntity => ({
  entity_id: "x.y",
  state,
  attributes,
  last_changed: "",
  last_updated: "",
});

const hass = { language: "pl", locale: { language: "pl" }, config: { time_zone: "Europe/Warsaw" } } as HomeAssistant;
const NOW = new Date("2026-11-12T12:00:00+01:00");
const days = (value?: string) => daysUntil(hass, value, NOW);

// The state seen on 12.11.2026: the November invoice paid online, not booked.
const lastInvoice = entity("27.4", {
  number: "P/12345678/0010/26",
  due_date: "2026-11-16",
  gross_amount: 27.4,
  state: "awaiting_booking",
  paid_at: "2026-11-10T11:09:07+00:00",
  automatic_payment_date: "2026-11-15",
  recent: [
    { number: "P/12345678/0010/26", due_date: "2026-11-16", gross_amount: 27.4, state: "awaiting_booking" },
    { number: "P/12345678/0009/26", due_date: "2026-10-16", gross_amount: 27.4, state: "paid" },
    { number: "bad", state: "weird" },
  ],
});

describe("payment", () => {
  it("is awaiting booking when paid online but not booked", () => {
    const payment = computePayment({
      toPay: entity("0.0", { awaiting_booking: 27.4 }),
      dueDate: entity("unknown"),
      lastInvoice,
      overdue: entity("off"),
    });
    expect(payment).toMatchObject({
      kind: "awaiting",
      amount: 27.4,
      due: "2026-11-16",
      paidAt: "2026-11-10T11:09:07+00:00",
      automatic: "2026-11-15",
    });
  });

  it("is to pay with the due invoice", () => {
    const payment = computePayment({
      toPay: entity("27.4", { awaiting_booking: 0 }),
      dueDate: entity("2026-11-16", { number: "P/1", automatic_payment_date: "2026-11-15" }),
      lastInvoice,
    });
    expect(payment).toMatchObject({ kind: "to_pay", amount: 27.4, due: "2026-11-16", invoice: "P/1" });
  });

  it("is overdue first", () => {
    const payment = computePayment({
      toPay: entity("27.4"),
      overdue: entity("on", { amount: 27.4, invoices: ["P/1"], since: "2026-11-16" }),
    });
    expect(payment).toMatchObject({ kind: "overdue", amount: 27.4, invoice: "P/1", due: "2026-11-16" });
  });

  it("is paid when nothing is due", () => {
    const paid = { ...lastInvoice, attributes: { ...lastInvoice.attributes, state: "paid" } };
    expect(computePayment({ toPay: entity("0.0"), lastInvoice: paid })).toMatchObject({ kind: "paid", amount: 27.4 });
    expect(computePayment({ toPay: entity("unavailable") }).kind).toBe("unknown");
  });
});

describe("alerts", () => {
  const options = withDefaults({ type: "" }).alerts;

  it("warns about a due date within the window", () => {
    const payment = { kind: "to_pay" as const, amount: 27.4, due: "2026-11-16" };
    expect(computeAlerts({ offline: false, payment }, options, days)).toEqual([{ type: "due_soon", days: 4 }]);
    expect(computeAlerts({ offline: false, payment }, { ...options, due_days: 2 }, days)).toEqual([]);
  });

  it("shows awaiting booking and a recent notice; offline hides the rest", () => {
    const payment = { kind: "awaiting" as const, amount: 27.4 };
    const notice = { title: "Phishing", message: "", date: "2026-11-10T08:00:00Z" };
    expect(computeAlerts({ offline: false, payment, notice }, options, days).map((a) => a.type)).toEqual([
      "awaiting_booking",
      "notice",
    ]);
    expect(computeAlerts({ offline: true, payment, notice }, options, days)).toEqual([{ type: "unavailable" }]);
    expect(computeAlerts({ offline: false, payment, notice }, { ...options, types: ["notice"] }, days)).toHaveLength(1);
  });

  it("drops an old notice", () => {
    const notice = { title: "Old", message: "", date: "2025-04-17T11:16:43Z" };
    expect(computeAlerts({ offline: false, payment: { kind: "paid" }, notice }, options, days)).toEqual([]);
  });
});

describe("attributes", () => {
  it("lists invoices with a known state", () => {
    expect(parseInvoices(lastInvoice).map((i) => i.state)).toEqual(["awaiting_booking", "paid", "unpaid"]);
    expect(parseInvoices(undefined)).toEqual([]);
  });

  it("reads the estimate breakdown and the notice", () => {
    const estimate = entity("19.73", { parts: [{ description: "Paliwo gazowe", gross: 2.67, kwh: 11 }] });
    expect(parseEstimateParts(estimate)).toEqual([{ description: "Paliwo gazowe", gross: 2.67, kwh: 11 }]);
    expect(parseNotice(entity("2026-11-12T10:00:00Z", { title: "Phishing", message: "Uwaga" }))).toEqual({
      title: "Phishing",
      message: "Uwaga",
      date: "2026-11-12T10:00:00Z",
    });
    expect(parseNotice(entity("unknown"))).toBeUndefined();
  });
});

describe("reading form", () => {
  it("validates the value against the last reading", () => {
    expect(checkReading("", 56)).toEqual({ ok: false, reason: "empty" });
    expect(checkReading("5a", 56)).toEqual({ ok: false, reason: "invalid" });
    expect(checkReading("57", 56)).toEqual({ ok: true, value: 57, lower: false, large: false });
    expect(checkReading("50,5", 56)).toMatchObject({ ok: true, value: 50.5, lower: true });
    expect(checkReading("600", 56)).toMatchObject({ ok: true, large: true });
    expect(checkReading("600")).toMatchObject({ ok: true, lower: false, large: false });
  });
});

describe("format", () => {
  it("keeps a bare date on its day", () => {
    expect(parseDate("2026-11-16")?.toISOString()).toBe("2026-11-16T12:00:00.000Z");
    expect(days("2026-11-16")).toBe(4);
    expect(formatDate(hass, "2026-11-16", NOW)).toBe("16.11");
    expect(formatDate(hass, "2025-04-17", NOW)).toBe("17.04.2025");
  });

  it("formats money in Polish", () => {
    expect(formatMoney(hass, 27.4).replace(/\s/g, " ")).toBe("27,40 zł");
  });
});

describe("editor", () => {
  it("prunes defaults", () => {
    const pruned = pruneConfig(
      { ...withDefaults({ type: "custom:myorlen-ebok-card" }), invoices: { count: 6 } },
      CARD_DEFAULTS as unknown as Record<string, unknown>,
    );
    expect(pruned).toEqual({ type: "custom:myorlen-ebok-card", invoices: { count: 6 } });
  });
});
