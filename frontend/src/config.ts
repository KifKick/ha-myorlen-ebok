// The card's options, their defaults, and the config with every default filled
// in. Kept apart from the card so the editor and the tests can use it without Lit.

import {
  ALERT_TYPES,
  type AlertType,
  type CardSection,
  type Color,
  DEFAULT_SECTIONS,
  DEFAULT_STATS,
  type HeaderInfo,
} from "./const";
import type { LovelaceCardConfig } from "./ha-types";

export type Layout = "default" | "compact" | "tile";

export interface CardConfig extends LovelaceCardConfig {
  device_id?: string;
  name?: string;
  icon?: string;
  layout?: Layout;
  accent_color?: Exclude<Color, "disabled" | "accent">;
  icon_shape?: "round" | "square";
  density?: "default" | "dense";
  header_info?: HeaderInfo;
  show_header?: boolean;
  section_titles?: boolean;
  sections?: CardSection[];
  alerts?: { types?: AlertType[]; due_days?: number; notice_days?: number };
  payment?: { show_pay_link?: boolean };
  invoices?: { count?: number };
  usage?: { show_estimate_parts?: boolean; show_add_reading?: boolean };
  stats?: string[];
}

export const CARD_DEFAULTS = {
  layout: "default",
  accent_color: "orlen",
  icon_shape: "round",
  density: "default",
  header_info: "summary",
  show_header: true,
  section_titles: true,
  sections: DEFAULT_SECTIONS,
  alerts: { types: [...ALERT_TYPES], due_days: 5, notice_days: 14 },
  payment: { show_pay_link: true },
  invoices: { count: 4 },
  usage: { show_estimate_parts: true, show_add_reading: true },
  stats: DEFAULT_STATS,
} as const;

/** The alert options, as the pure logic in model.ts takes them. */
export interface AlertOptions {
  types: AlertType[];
  due_days: number;
  notice_days: number;
}

/** The config with every option set. */
export interface FullCardConfig extends CardConfig {
  layout: Layout;
  accent_color: NonNullable<CardConfig["accent_color"]>;
  icon_shape: "round" | "square";
  density: "default" | "dense";
  header_info: HeaderInfo;
  show_header: boolean;
  section_titles: boolean;
  sections: CardSection[];
  alerts: AlertOptions;
  payment: { show_pay_link: boolean };
  invoices: { count: number };
  usage: { show_estimate_parts: boolean; show_add_reading: boolean };
  stats: string[];
}

const GROUPS = ["alerts", "payment", "invoices", "usage"] as const;

/** The config with every default filled in, section options included. */
export const withDefaults = (config: CardConfig): FullCardConfig => {
  const full: Record<string, unknown> = { ...CARD_DEFAULTS, ...config };
  for (const group of GROUPS) {
    full[group] = { ...CARD_DEFAULTS[group], ...(config[group] as object | undefined) };
  }
  return full as unknown as FullCardConfig;
};
