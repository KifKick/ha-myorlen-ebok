// The card's visual editor: a plain <ha-form> (HA's own selectors), laid out
// like the other KifKick cards' editors: the meter picker at the root, how the
// card looks in one collapsible group, then one group per section. Values equal
// to the defaults are dropped, so the YAML stays minimal.

import { html, LitElement, nothing } from "lit";
import { property, state } from "lit/decorators.js";

import { CARD_DEFAULTS, type CardConfig, withDefaults } from "./config";
import { ALERT_TYPES, CARD_SECTIONS, COLORS, DOMAIN, HEADER_INFO, STATS } from "./const";
import { getMeterDevices } from "./discovery";
import { fireEvent, type HomeAssistant } from "./ha-types";
import { type StringKey, t } from "./i18n";

type Schema = Record<string, unknown>;

const options = (hass: HomeAssistant | undefined, values: readonly string[], prefix: string) =>
  values.map((value) => ({ value, label: t(hass, `${prefix}${value}` as StringKey) }));

/** Ordered multi-select: the order the user picks is the order shown on the card. */
const multiSelect = (hass: HomeAssistant | undefined, values: readonly string[], prefix: string) => ({
  selector: { select: { multiple: true, reorder: true, mode: "list", options: options(hass, values, prefix) } },
});

const choice = (hass: HomeAssistant | undefined, values: readonly string[], prefix: string, mode = "box") => ({
  selector: { select: { mode, options: options(hass, values, prefix) } },
});

const toggle = { selector: { boolean: {} } };

const number = (min: number, max: number, step = 1) => ({ selector: { number: { min, max, step, mode: "box" } } });

const grid = (schema: Schema[]): Schema => ({ type: "grid", name: "", schema });

const LABEL_KEYS: Record<string, StringKey> = {
  device_id: "ed_device_id",
  name: "ed_name",
  icon: "ed_icon",
  layout: "ed_layout",
  accent_color: "ed_accent_color",
  icon_shape: "ed_icon_shape",
  density: "ed_density",
  header_info: "ed_header_info",
  show_header: "ed_show_header",
  section_titles: "ed_section_titles",
  sections: "ed_sections",
  types: "ed_types",
  due_days: "ed_due_days",
  notice_days: "ed_notice_days",
  show_pay_link: "ed_show_pay_link",
  count: "ed_count",
  show_estimate_parts: "ed_show_estimate_parts",
  show_add_reading: "ed_show_add_reading",
  stats: "ed_stats",
};

const HELPER_KEYS: Record<string, StringKey> = { sections: "ed_sections_helper" };

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Drops empty values and values equal to the defaults, section objects included. */
export const pruneConfig = (config: Record<string, unknown>, defaults: Record<string, unknown>): Record<string, unknown> => {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (value === undefined || value === null || value === "") continue;
    const fallback = defaults[key];
    if (isObject(value) && isObject(fallback)) {
      const inner = pruneConfig(value, fallback);
      if (Object.keys(inner).length) out[key] = inner;
    } else if (!(key in defaults) || JSON.stringify(value) !== JSON.stringify(fallback)) {
      out[key] = value;
    }
  }
  return out;
};

export class MyOrlenCardEditor extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;

  @state() private _config?: CardConfig;

  setConfig(config: CardConfig): void {
    this._config = config;
  }

  private _schema(): Schema[] {
    const hass = this.hass;
    const cfg = withDefaults(this._config ?? { type: "" });
    const full = cfg.layout === "default";
    const appearance: Schema = {
      name: "",
      type: "expandable",
      flatten: true,
      icon: "mdi:palette-outline",
      title: t(hass, "ed_appearance"),
      schema: [
        grid([
          { name: "name", selector: { text: {} } },
          { name: "icon", selector: { icon: {} } },
        ]),
        { name: "layout", ...choice(hass, ["default", "compact", "tile"], "ed_layout_") },
        grid([
          { name: "accent_color", ...choice(hass, COLORS, "color_", "dropdown") },
          { name: "header_info", ...choice(hass, HEADER_INFO, "ed_header_info_", "dropdown") },
          { name: "icon_shape", ...choice(hass, ["round", "square"], "ed_icon_shape_", "dropdown") },
          { name: "density", ...choice(hass, ["default", "dense"], "ed_density_", "dropdown") },
        ]),
        ...(full
          ? [
              { name: "sections", ...multiSelect(hass, CARD_SECTIONS, "ed_section_") },
              grid([
                { name: "show_header", ...toggle },
                { name: "section_titles", ...toggle },
              ]),
            ]
          : []),
      ],
    };
    const group = (name: string, icon: string, schema: Schema[]): Schema => ({
      name,
      type: "expandable",
      icon,
      title: t(hass, `ed_section_${name}` as StringKey),
      schema,
    });
    const alerts = group("alerts", "mdi:alert-circle-outline", [
      ...(full ? [{ name: "types", ...multiSelect(hass, ALERT_TYPES, "alert_type_") }] : []),
      grid([
        { name: "due_days", ...number(0, 31) },
        ...(full ? [{ name: "notice_days", ...number(0, 365) }] : []),
      ]),
    ]);
    if (!full) return [this._deviceSchema(), appearance, alerts];

    return [
      this._deviceSchema(),
      appearance,
      alerts,
      group("payment", "mdi:cash-clock", [{ name: "show_pay_link", ...toggle }]),
      group("invoices", "mdi:receipt-text-outline", [{ name: "count", ...number(1, 12) }]),
      group("usage", "mdi:meter-gas-outline", [
        grid([
          { name: "show_estimate_parts", ...toggle },
          { name: "show_add_reading", ...toggle },
        ]),
      ]),
      {
        name: "",
        type: "expandable",
        flatten: true,
        icon: "mdi:counter",
        title: t(hass, "ed_section_stats"),
        schema: [{ name: "stats", ...multiSelect(hass, Object.keys(STATS), "stat_") }],
      },
    ];
  }

  private _deviceSchema(): Schema {
    return { name: "device_id", required: true, selector: { device: { filter: { integration: DOMAIN } } } };
  }

  protected override render() {
    if (!this.hass || !this._config) return nothing;
    const noDevices = getMeterDevices(this.hass).length === 0;
    return html`<ha-form
      .hass=${this.hass}
      .data=${withDefaults(this._config)}
      .schema=${this._schema()}
      .computeLabel=${(schema: Schema) =>
        LABEL_KEYS[schema.name as string] ? t(this.hass, LABEL_KEYS[schema.name as string]) : undefined}
      .computeHelper=${(schema: Schema) =>
        schema.name === "device_id" && noDevices
          ? t(this.hass, "ed_no_devices")
          : HELPER_KEYS[schema.name as string]
            ? t(this.hass, HELPER_KEYS[schema.name as string])
            : undefined}
      @value-changed=${this._valueChanged}
    ></ha-form>`;
  }

  private _valueChanged(ev: CustomEvent): void {
    ev.stopPropagation();
    const config = pruneConfig(ev.detail.value, CARD_DEFAULTS as unknown as Record<string, unknown>);
    fireEvent(this, "config-changed", { config: { type: this._config?.type, ...config } });
  }
}
