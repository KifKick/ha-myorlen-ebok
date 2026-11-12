// Number, money and date formatting that follows the user's Home Assistant locale.

import type { HassEntity, HomeAssistant } from "./ha-types";
import { language } from "./i18n";

/** Mirrors HA's numberFormat preference so numbers match the rest of the UI. */
export const numberLocale = (hass?: HomeAssistant): string | string[] | undefined => {
  const lang = hass?.locale?.language ?? hass?.language;
  switch (hass?.locale?.number_format) {
    case "comma_decimal":
      return ["en-US", "en"];
    case "decimal_comma":
      return ["de", "es", "it"];
    case "space_comma":
      return ["fr", "sv", "cs"];
    case "system":
      return undefined;
    default:
      return lang;
  }
};

/** A number with up to `maxDigits` decimals (and at least `minDigits`). */
export const formatNumber = (hass: HomeAssistant | undefined, value: number, maxDigits = 0, minDigits = 0): string =>
  new Intl.NumberFormat(numberLocale(hass), {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: Math.max(minDigits, maxDigits),
  }).format(value);

/** 27.4 -> "27,40 zł" in Polish, "PLN 27.40" in English. */
export const formatMoney = (hass: HomeAssistant | undefined, amount: number, currency = "PLN"): string => {
  try {
    return new Intl.NumberFormat(numberLocale(hass), { style: "currency", currency }).format(amount);
  } catch {
    return `${formatNumber(hass, amount, 2, 2)} ${currency}`;
  }
};

/** 56 -> "56 m³"; up to 3 decimals. */
export const formatVolume = (hass: HomeAssistant | undefined, m3: number): string => `${formatNumber(hass, m3, 3)} m³`;

/** HA's time zone setting: the server's, or the browser's. */
const timeZone = (hass?: HomeAssistant): string | undefined =>
  hass?.locale?.time_zone === "local" ? undefined : hass?.config?.time_zone;

/**
 * A date or date-time string. A bare "YYYY-MM-DD" is a calendar day: it is read
 * as noon UTC so it stays the same day in any time zone.
 */
export const parseDate = (value?: string | null): Date | undefined => {
  if (!value) return undefined;
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00Z` : value);
  return Number.isNaN(date.getTime()) ? undefined : date;
};

const dateKey = (hass: HomeAssistant | undefined, date: Date, bareDay = false): string =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: bareDay ? "UTC" : timeZone(hass),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);

const isBareDay = (value?: string | null): boolean => Boolean(value && /^\d{4}-\d{2}-\d{2}$/.test(value));

/** "16.11" (or "16 Nov"), with the year only when it is not this year's. */
export const formatDate = (hass: HomeAssistant | undefined, value?: string | null, now = new Date()): string => {
  const date = parseDate(value);
  if (!date) return "";
  const bare = isBareDay(value);
  const sameYear = dateKey(hass, date, bare).slice(0, 4) === dateKey(hass, now).slice(0, 4);
  return new Intl.DateTimeFormat(language(hass), {
    timeZone: bare ? "UTC" : timeZone(hass),
    day: "numeric",
    month: language(hass) === "pl" ? "2-digit" : "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
};

/** Whole calendar days from today until `value` in HA's time zone (0 = today). */
export const daysUntil = (hass: HomeAssistant | undefined, value?: string | null, now = new Date()): number | undefined => {
  const date = parseDate(value);
  if (!date) return undefined;
  const a = Date.parse(dateKey(hass, now));
  const b = Date.parse(dateKey(hass, date, isBareDay(value)));
  return Math.round((b - a) / 86_400_000);
};

/** "today", "tomorrow", "in 4 days", "3 days ago", in the user's language. */
export const formatRelativeDays = (hass: HomeAssistant | undefined, days: number): string => {
  try {
    return new Intl.RelativeTimeFormat(language(hass), { numeric: "auto" }).format(days, "day");
  } catch {
    return String(days);
  }
};

export const isUnavailable = (stateObj?: HassEntity): boolean =>
  !stateObj || stateObj.state === "unavailable" || stateObj.state === "unknown";
