import { css, html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { property, state } from "lit/decorators.js";

import { type CardConfig, type FullCardConfig, withDefaults } from "./config";
import { ADD_READING_SERVICE, type CardSection, type Color, DOMAIN, ENTITY, MAX_READING_INCREASE_M3, STATS } from "./const";
import { type EntityMap, getMeterDevices, resolveDevice, resolveEntities } from "./discovery";
import {
  daysUntil,
  formatDate,
  formatMoney,
  formatNumber,
  formatRelativeDays,
  formatVolume,
  isUnavailable,
} from "./format";
import { type DeviceRegistryEntry, fireEvent, type HassEntity, type HomeAssistant } from "./ha-types";
import { type StringKey, t } from "./i18n";
import {
  type Alert,
  checkReading,
  computeAlerts,
  computePayment,
  type EstimatePart,
  type InvoiceRow,
  type Notice,
  num,
  type Payment,
  type PaymentKind,
  parseEstimateParts,
  parseInvoices,
  parseNotice,
  stateOf,
} from "./model";
import { baseStyles } from "./styles";

export const rgb = (color: Color): string => `var(--rgb-${color})`;

/** Keyboard activation for non-button elements with role="button". */
const onActivate =
  (handler: () => void) =>
  (ev: KeyboardEvent): void => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      handler();
    }
  };

/** HA's form elements load lazily; borrow a built-in card editor to load them. */
export const loadHaForm = async (): Promise<void> => {
  if (customElements.get("ha-form")) return;
  const helpers = await (window as any).loadCardHelpers?.();
  const card = await helpers?.createCardElement({ type: "tile", entity: "sun.sun" });
  await card?.constructor?.getConfigElement?.();
};

const PAYMENT_COLOR: Record<PaymentKind, string> = {
  overdue: "var(--rgb-red)",
  to_pay: "var(--rgb-accent)",
  awaiting: "var(--rgb-blue)",
  paid: "var(--rgb-green)",
  unknown: "var(--rgb-disabled)",
};

const INVOICE_COLOR: Record<InvoiceRow["state"], string> = {
  unpaid: "var(--rgb-accent)",
  awaiting_booking: "var(--rgb-blue)",
  paid: "var(--rgb-green)",
};

const INVOICE_ICON: Record<InvoiceRow["state"], string> = {
  unpaid: "mdi:receipt-text-clock-outline",
  awaiting_booking: "mdi:receipt-text-send-outline",
  paid: "mdi:receipt-text-check-outline",
};

interface Snapshot {
  payment: Payment;
  invoices: InvoiceRow[];
  reading?: number;
  readingDate?: string;
  readingUsage?: number;
  tariff?: string;
  cost?: number;
  invoiceM3?: number;
  invoiceKwh?: number;
  estimate?: number;
  estimateParts: EstimatePart[];
  balance?: number;
  agreement?: string;
  agreementStart?: string;
  lastPayment?: number;
  lastPaymentDate?: string;
  notice?: Notice;
  alerts: Alert[];
}

/** The reading dialog's form. */
interface ReadingForm {
  value: string;
  date: string;
  reset: boolean;
  large: boolean;
  confirmed: boolean;
  error?: string;
}

/**
 * The myORLEN eBOK card: a header for the gas meter, then whichever sections
 * the config lists (alerts, payment, invoices, usage, account, counters).
 */
export class MyOrlenCard extends LitElement {
  static getStubConfig(hass: HomeAssistant): Partial<CardConfig> {
    const device = getMeterDevices(hass)[0];
    return device ? { device_id: device.id } : {};
  }

  static async getConfigElement(): Promise<HTMLElement> {
    await loadHaForm();
    return document.createElement("myorlen-ebok-card-editor");
  }

  /** Set by HA ("grid" in sections views); reflected so styles can fill the cell. */
  @property({ reflect: true }) layout?: string;

  @state() private _config?: CardConfig;

  @state() private _reading?: ReadingForm;

  @state() private _busy = false;

  private _full = withDefaults({ type: "" });

  private _hass?: HomeAssistant;

  set hass(hass: HomeAssistant) {
    const previous = this._hass;
    this._hass = hass;
    this.toggleAttribute("dark-mode", Boolean(hass.themes?.darkMode));
    if (
      !previous ||
      previous.entities !== hass.entities ||
      previous.devices !== hass.devices ||
      previous.locale !== hass.locale ||
      Object.values(this._entities).some((id) => previous.states[id] !== hass.states[id])
    ) {
      this.requestUpdate();
    }
  }

  get hass(): HomeAssistant | undefined {
    return this._hass;
  }

  setConfig(config: CardConfig): void {
    this._config = config;
    this._full = withDefaults(config);
  }

  private get _cfg(): FullCardConfig {
    return this._full;
  }

  // --- Data ------------------------------------------------------------------------

  private get _device(): DeviceRegistryEntry | undefined {
    return this._hass ? resolveDevice(this._hass, this._config?.device_id) : undefined;
  }

  private get _entities(): EntityMap {
    const device = this._device;
    return device && this._hass ? resolveEntities(this._hass, device.id) : {};
  }

  private _stateObj(key: string): HassEntity | undefined {
    const entityId = this._entities[key];
    return entityId ? this._hass?.states[entityId] : undefined;
  }

  private _attr(key: string, name: string): unknown {
    return this._stateObj(key)?.attributes?.[name];
  }

  /** The meter's sensors are missing or have no data (integration down, login expired). */
  private get _offline(): boolean {
    return isUnavailable(this._stateObj(ENTITY.toPay)) && isUnavailable(this._stateObj(ENTITY.reading));
  }

  private _days = (value?: string): number | undefined => daysUntil(this._hass, value);

  private _snapshot(): Snapshot {
    const payment = computePayment({
      toPay: this._stateObj(ENTITY.toPay),
      dueDate: this._stateObj(ENTITY.dueDate),
      lastInvoice: this._stateObj(ENTITY.lastInvoice),
      overdue: this._stateObj(ENTITY.overdue),
    });
    const notice = parseNotice(this._stateObj(ENTITY.notices));
    const str = (value: unknown) => (typeof value === "string" && value ? value : undefined);
    return {
      payment,
      invoices: parseInvoices(this._stateObj(ENTITY.lastInvoice)),
      reading: num(stateOf(this._stateObj(ENTITY.reading))),
      readingDate: str(this._attr(ENTITY.reading, "reading_date")),
      readingUsage: num(this._attr(ENTITY.reading, "usage")),
      tariff: str(this._attr(ENTITY.reading, "tariff")) ?? str(this._attr(ENTITY.balance, "tariff")),
      cost: num(stateOf(this._stateObj(ENTITY.costPerM3))),
      invoiceM3: num(this._attr(ENTITY.lastInvoice, "usage_m3")),
      invoiceKwh: num(this._attr(ENTITY.lastInvoice, "usage_kwh")),
      estimate: num(stateOf(this._stateObj(ENTITY.billEstimate))),
      estimateParts: parseEstimateParts(this._stateObj(ENTITY.billEstimate)),
      balance: num(stateOf(this._stateObj(ENTITY.balance))),
      agreement: str(this._attr(ENTITY.balance, "agreement")),
      agreementStart: str(this._attr(ENTITY.balance, "agreement_start")),
      lastPayment: num(stateOf(this._stateObj(ENTITY.lastPayment))),
      lastPaymentDate: str(this._attr(ENTITY.lastPayment, "date")),
      notice,
      alerts: computeAlerts({ offline: this._offline, payment, notice }, this._cfg.alerts, this._days),
    };
  }

  // --- Actions ---------------------------------------------------------------------

  private _moreInfo(key: string): void {
    const entityId = this._entities[key];
    if (entityId) fireEvent(this, "hass-more-info", { entityId });
  }

  private _toast(message: string): void {
    fireEvent(this, "hass-notification", { message });
  }

  private _today(): string {
    return new Intl.DateTimeFormat("en-CA", { timeZone: this._hass?.config?.time_zone }).format(new Date());
  }

  private _openReading(): void {
    this._reading = { value: "", date: this._today(), reset: false, large: false, confirmed: false };
  }

  private _closeReading(): void {
    if (!this._busy) this._reading = undefined;
  }

  private async _submitReading(ev: Event, last?: number): Promise<void> {
    ev.preventDefault();
    const hass = this._hass;
    const form = this._reading;
    const device = this._device;
    if (!hass || !form || !device || this._busy || !form.confirmed) return;
    const check = checkReading(form.value, last);
    if (!check.ok || (check.lower && !form.reset) || (check.large && !form.large)) return;
    this._busy = true;
    const value = formatVolume(hass, check.value);
    try {
      // notifyOnError off: the dialog shows the error itself.
      const result = (await hass.callService(
        DOMAIN,
        ADD_READING_SERVICE,
        {
          device_id: device.id,
          value: check.value,
          date: form.date || undefined,
          meter_reset: form.reset,
          confirm_large_increase: form.large,
        },
        undefined,
        false,
        true,
      )) as { response?: { can_be_cancelled?: boolean } } | undefined;
      this._reading = undefined;
      this._toast(t(hass, result?.response?.can_be_cancelled ? "reading_done_cancel" : "reading_done", { value }));
    } catch (err: any) {
      const message = t(hass, "reading_failed", { error: String(err?.message ?? err) });
      this._reading = { ...form, confirmed: false, error: message };
    } finally {
      this._busy = false;
    }
  }

  // --- Size ------------------------------------------------------------------------

  getCardSize(): number {
    if (this._cfg.layout !== "default") return this._cfg.layout === "tile" ? 2 : 1;
    if (this._offline || !this._hass) return 2;
    const data = this._snapshot();
    let size = this._cfg.show_header ? 1 : 0;
    for (const section of this._cfg.sections) {
      if (section === "alerts") size += data.alerts.length;
      else if (section === "invoices") size += 1 + Math.min(this._cfg.invoices.count, data.invoices.length);
      else if (section === "stats") size += 1;
      else size += 3;
    }
    return Math.max(1, size);
  }

  getGridOptions() {
    switch (this._cfg.layout) {
      case "compact":
        return { columns: 6, rows: 1, min_columns: 4, min_rows: 1 };
      case "tile":
        return { columns: 3, rows: 2, min_columns: 3, min_rows: 2 };
      default:
        return { columns: 12, rows: "auto", min_columns: 6 };
    }
  }

  protected override updated(changed: PropertyValues): void {
    super.updated(changed);
    if (changed.has("_config")) {
      const cfg = this._cfg;
      this.style.setProperty("--myorlen-accent", rgb(cfg.accent_color));
      this.toggleAttribute("square", cfg.icon_shape === "square");
      this.toggleAttribute("dense", cfg.density === "dense");
    }
    const dialog = this.renderRoot.querySelector<HTMLDialogElement>("dialog.sheet");
    if (dialog && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLInputElement>("input[inputmode]")?.focus();
    }
  }

  // --- Render ----------------------------------------------------------------------

  protected override render() {
    if (!this._config || !this._hass) return nothing;
    const hass = this._hass;
    if (!this._device) {
      return html`<ha-card>
        <div class="message"><ha-icon icon="mdi:alert-circle-outline"></ha-icon>${t(hass, "no_device")}</div>
      </ha-card>`;
    }
    const data = this._snapshot();
    if (this._cfg.layout === "compact") return this._renderCompact(data);
    if (this._cfg.layout === "tile") return this._renderTile(data);
    const header = this._cfg.show_header ? this._renderHeader(data) : nothing;
    if (this._offline) return html`<ha-card>${header}${this._renderOffline()}</ha-card>`;
    const sections = this._cfg.sections
      .map((section) => this._renderSection(section, data))
      .filter((section) => section !== nothing);
    return html`<ha-card>
        ${header}
        ${sections.length
          ? html`<div class="body ${this._cfg.show_header ? "" : "headless"}">${sections}</div>`
          : nothing}
      </ha-card>
      ${this._renderReadingDialog(data)}`;
  }

  private _renderOffline(): TemplateResult {
    const hass = this._hass!;
    return html`<div class="message">
      <ha-icon icon="mdi:cloud-off-outline"></ha-icon>
      <span>${this._cfg.show_header ? nothing : html`<b>${t(hass, "offline")}</b><br />`}${t(hass, "offline_hint")}</span>
    </div>`;
  }

  private get _name(): string {
    if (this._cfg.name) return this._cfg.name;
    const device = this._device;
    // The integration names the device after the long meter number; a user's own name wins.
    return device?.name_by_user || t(this._hass, "default_name");
  }

  private _money(amount?: number): string {
    return amount === undefined ? "—" : formatMoney(this._hass, amount);
  }

  private _when(value?: string): string {
    const days = this._days(value);
    return days === undefined ? "" : days < 0 ? formatDate(this._hass, value) : formatRelativeDays(this._hass, days);
  }

  private _renderBadge(data: Snapshot): TemplateResult | typeof nothing {
    if (this._offline) return nothing;
    const badge = (color: string, icon: string) =>
      html`<div class="badge" style="--badge-c: ${color}"><ha-icon icon=${icon}></ha-icon></div>`;
    if (data.payment.kind === "overdue") return badge("var(--rgb-red)", "mdi:exclamation-thick");
    if (data.alerts.some((a) => a.type === "due_soon")) return badge("var(--rgb-amber)", "mdi:clock-outline");
    if (data.payment.kind === "awaiting") return badge("var(--rgb-blue)", "mdi:timer-sand");
    return nothing;
  }

  private _renderIcon(data: Snapshot, extraClass = ""): TemplateResult {
    return html`<div class="shape ${extraClass}" style="--c: var(--rgb-accent)">
      <ha-icon .icon=${this._cfg.icon ?? "mdi:fire"}></ha-icon>${this._renderBadge(data)}
    </div>`;
  }

  /** The header's second line, as the config picks it. */
  private _headerInfo(data: Snapshot, short = false): string {
    const hass = this._hass!;
    if (this._offline) return t(hass, "offline");
    switch (this._cfg.header_info) {
      case "reading":
        return data.reading !== undefined ? t(hass, "reading_line", { value: formatVolume(hass, data.reading) }) : "";
      case "balance":
        return data.balance !== undefined ? t(hass, "balance_line", { amount: this._money(data.balance) }) : "";
      case "none":
        return "";
      default:
        return this._summary(data, short);
    }
  }

  private _summary(data: Snapshot, short = false): string {
    const hass = this._hass!;
    const { payment } = data;
    const amount = this._money(payment.amount);
    switch (payment.kind) {
      case "overdue":
        return t(hass, "summary_overdue", { amount });
      case "to_pay": {
        const when = this._when(payment.due);
        const text = t(hass, "summary_to_pay", { amount });
        return when && !short ? `${text} · ${t(hass, "summary_due", { when })}` : text;
      }
      case "awaiting":
        return t(hass, "summary_awaiting", { amount });
      case "paid":
        return t(hass, "summary_paid");
      default:
        return "";
    }
  }

  private _renderHeader(data: Snapshot) {
    const moreInfo = () => this._moreInfo(ENTITY.toPay);
    const info = this._headerInfo(data);
    return html`<div class="state-item header">
      ${this._renderIcon(data)}
      <div class="info clickable" role="button" tabindex="0" @click=${moreInfo} @keydown=${onActivate(moreInfo)}>
        <span class="primary">${this._name}</span>
        ${info ? html`<span class="secondary">${info}</span>` : nothing}
      </div>
      ${this._renderEbokLink()}
    </div>`;
  }

  private _renderEbokLink(): TemplateResult | typeof nothing {
    const url = this._device?.configuration_url;
    return url
      ? html`<a class="icon-button" href=${url} target="_blank" rel="noreferrer" title=${t(this._hass, "open_ebok")}
          ><ha-icon icon="mdi:open-in-new"></ha-icon
        ></a>`
      : nothing;
  }

  /** One row: icon, name, summary, and the amount on the right. */
  private _renderCompact(data: Snapshot) {
    const moreInfo = () => this._moreInfo(ENTITY.toPay);
    const info = this._headerInfo(data, true);
    const { payment } = data;
    return html`<ha-card class="compact" style="--c: ${PAYMENT_COLOR[payment.kind]}">
      <div class="state-item">
        ${this._renderIcon(data)}
        <div class="info clickable" role="button" tabindex="0" @click=${moreInfo} @keydown=${onActivate(moreInfo)}>
          <span class="primary">${this._name}</span>
          ${info ? html`<span class="secondary">${info}</span>` : nothing}
        </div>
        ${!this._offline && payment.kind !== "unknown" && payment.kind !== "paid"
          ? html`<span class="compact-amount">${this._money(payment.amount)}</span>`
          : nothing}
      </div>
    </ha-card>`;
  }

  /** Mushroom's vertical layout: icon on top, centred text. */
  private _renderTile(data: Snapshot) {
    const moreInfo = () => this._moreInfo(ENTITY.toPay);
    const info = this._headerInfo(data, true);
    return html`<ha-card
      class="tile clickable"
      role="button"
      tabindex="0"
      @click=${moreInfo}
      @keydown=${onActivate(moreInfo)}
    >
      ${this._renderIcon(data, "large")}
      <span class="primary">${this._name}</span>
      ${info ? html`<span class="secondary">${info}</span>` : nothing}
    </ha-card>`;
  }

  private _titled(title: string, content: TemplateResult, detail?: string) {
    return html`<div class="section titled">
      ${this._cfg.section_titles
        ? html`<div class="caption">
            <span class="caption-title">${title}</span>${detail ? html`<span class="caption-detail">${detail}</span>` : nothing}
          </div>`
        : nothing}
      <div class="pad">${content}</div>
    </div>`;
  }

  private _renderSection(section: CardSection, data: Snapshot): TemplateResult | typeof nothing {
    const hass = this._hass!;
    switch (section) {
      case "alerts":
        return data.alerts.length
          ? html`<div class="section pad alerts">${data.alerts.map((alert) => this._renderAlert(alert, data))}</div>`
          : nothing;
      case "payment":
        return this._entities[ENTITY.toPay] ? this._titled(t(hass, "payment_title"), this._renderPayment(data)) : nothing;
      case "invoices":
        return this._entities[ENTITY.lastInvoice]
          ? this._titled(t(hass, "invoices_title"), this._renderInvoices(data))
          : nothing;
      case "usage":
        return this._entities[ENTITY.reading] ? this._titled(t(hass, "usage_title"), this._renderUsage(data)) : nothing;
      case "account":
        return this._entities[ENTITY.balance] || this._entities[ENTITY.lastPayment]
          ? this._titled(t(hass, "account_title"), this._renderAccount(data))
          : nothing;
      case "stats": {
        const chips = this._renderStats(data);
        return chips === nothing ? nothing : html`<div class="section pad">${chips}</div>`;
      }
      default:
        return nothing;
    }
  }

  // --- Alerts ----------------------------------------------------------------------

  private _banner(color: string, icon: string, title: string, secondary: string, onClick?: () => void) {
    return html`<div
      class="banner ${onClick ? "clickable" : ""}"
      style="--c: ${color}"
      role=${onClick ? "button" : nothing}
      tabindex=${onClick ? "0" : nothing}
      @click=${onClick ?? nothing}
      @keydown=${onClick ? onActivate(onClick) : nothing}
    >
      <div class="shape"><ha-icon .icon=${icon}></ha-icon></div>
      <div class="info">
        <span class="primary">${title}</span>
        ${secondary ? html`<span class="secondary" title=${secondary}>${secondary}</span>` : nothing}
      </div>
    </div>`;
  }

  private _renderAlert(alert: Alert, data: Snapshot): TemplateResult {
    const hass = this._hass!;
    const { payment } = data;
    const amount = this._money(payment.amount);
    const date = formatDate(hass, payment.due);
    switch (alert.type) {
      case "unavailable":
        return this._banner(
          "var(--rgb-grey)",
          "mdi:cloud-off-outline",
          t(hass, "alert_unavailable"),
          t(hass, "alert_unavailable_hint"),
        );
      case "overdue":
        return this._banner(
          "var(--rgb-red)",
          "mdi:alert-circle-outline",
          t(hass, "alert_overdue", { amount }),
          date ? t(hass, "alert_overdue_hint", { date }) : "",
          () => this._moreInfo(ENTITY.overdue),
        );
      case "due_soon":
        return this._banner(
          "var(--rgb-amber)",
          "mdi:calendar-clock-outline",
          t(hass, "alert_due_soon", { amount, when: formatRelativeDays(hass, alert.days ?? 0) }),
          payment.automatic
            ? t(hass, "alert_due_soon_auto", { date, auto: formatDate(hass, payment.automatic) })
            : t(hass, "alert_due_soon_hint", { date }),
          () => this._moreInfo(ENTITY.dueDate),
        );
      case "awaiting_booking":
        return this._banner(
          "var(--rgb-blue)",
          "mdi:timer-sand",
          t(hass, "alert_awaiting_booking", { amount }),
          payment.paidAt
            ? t(hass, "alert_awaiting_booking_hint", { date: formatDate(hass, payment.paidAt) })
            : t(hass, "alert_awaiting_booking_nodate"),
          () => this._moreInfo(ENTITY.lastInvoice),
        );
      case "notice":
        return this._banner(
          "var(--rgb-deep-orange)",
          "mdi:bullhorn-outline",
          t(hass, "alert_notice", { title: data.notice?.title ?? "" }),
          data.notice?.message ?? "",
          () => this._moreInfo(ENTITY.notices),
        );
    }
  }

  // --- Payment ---------------------------------------------------------------------

  private _renderPayment(data: Snapshot): TemplateResult {
    const hass = this._hass!;
    const { payment } = data;
    const lines: string[] = [];
    if (payment.kind === "overdue" && payment.due) {
      lines.push(t(hass, "overdue_since", { date: formatDate(hass, payment.due) }));
    } else if (payment.kind === "paid" && payment.due) {
      lines.push(t(hass, "last_invoice_paid", { amount: this._money(payment.amount), date: formatDate(hass, payment.due) }));
    } else if (payment.due) {
      lines.push(t(hass, "due_on", { date: formatDate(hass, payment.due), when: this._when(payment.due) }));
    }
    if (payment.automatic && payment.kind !== "paid") {
      lines.push(t(hass, "automatic_on", { date: formatDate(hass, payment.automatic) }));
    }
    if (payment.paidAt) lines.push(t(hass, "paid_at", { date: formatDate(hass, payment.paidAt) }));
    if (payment.invoice) lines.push(t(hass, "invoice_no", { number: payment.invoice }));

    const shown = payment.kind === "paid" ? 0 : payment.amount;
    const pay =
      this._cfg.payment.show_pay_link &&
      (payment.kind === "to_pay" || payment.kind === "overdue") &&
      this._device?.configuration_url;
    const moreInfo = () => this._moreInfo(ENTITY.toPay);
    return html`<div class="hero" style="--c: ${PAYMENT_COLOR[payment.kind]}">
      <div class="hero-head clickable" role="button" tabindex="0" @click=${moreInfo} @keydown=${onActivate(moreInfo)}>
        <span class="hero-value">${this._money(shown)}</span>
        <span class="pill">${t(hass, `pay_state_${payment.kind}` as StringKey)}</span>
      </div>
      ${lines.map((line) => html`<span class="hero-line">${line}</span>`)}
      ${pay
        ? html`<div class="hero-actions">
            <a class="button accent small-button" href=${this._device!.configuration_url!} target="_blank" rel="noreferrer">
              <ha-icon icon="mdi:credit-card-outline"></ha-icon>${t(hass, "pay_in_ebok")}
            </a>
          </div>`
        : nothing}
    </div>`;
  }

  // --- Invoices --------------------------------------------------------------------

  private _renderInvoices(data: Snapshot): TemplateResult {
    const hass = this._hass!;
    const rows = data.invoices.slice(0, this._cfg.invoices.count);
    if (!rows.length) return html`<div class="empty">${t(hass, "no_invoices")}</div>`;
    const open = () => this._moreInfo(this._entities[ENTITY.invoices] ? ENTITY.invoices : ENTITY.lastInvoice);
    return html`<div class="rows">
      ${rows.map(
        (row) => html`<div
          class="state-item row-item clickable"
          role="button"
          tabindex="0"
          @click=${open}
          @keydown=${onActivate(open)}
        >
          <div class="shape small" style="--c: ${INVOICE_COLOR[row.state]}">
            <ha-icon .icon=${INVOICE_ICON[row.state]}></ha-icon>
          </div>
          <div class="info">
            <span class="primary">${this._money(row.amount)}</span>
            <span class="secondary"
              >${[row.due ? t(hass, "inv_due", { date: formatDate(hass, row.due) }) : "", row.number]
                .filter(Boolean)
                .join(" · ")}</span
            >
          </div>
          <span class="pill" style="--c: ${INVOICE_COLOR[row.state]}">${t(hass, `inv_${row.state}` as StringKey)}</span>
        </div>`,
      )}
    </div>`;
  }

  // --- Usage -----------------------------------------------------------------------

  private _renderUsage(data: Snapshot): TemplateResult {
    const hass = this._hass!;
    const sub = [
      data.readingDate ? t(hass, "reading_on", { date: formatDate(hass, data.readingDate) }) : "",
      data.readingUsage !== undefined
        ? t(hass, "reading_usage", { value: formatVolume(hass, data.readingUsage) })
        : "",
    ].filter(Boolean);
    const moreInfo = () => this._moreInfo(ENTITY.reading);
    const canSubmit = this._cfg.usage.show_add_reading && this._hass;
    return html`<div class="usage" style="--c: var(--rgb-blue)">
      <div class="usage-row">
        <div class="usage-head clickable" role="button" tabindex="0" @click=${moreInfo} @keydown=${onActivate(moreInfo)}>
          <span class="usage-value"
            >${data.reading !== undefined ? formatNumber(hass, data.reading, 3) : "—"}<small>m³</small></span
          >
          ${sub.length ? html`<span class="usage-line">${sub.join(" · ")}</span>` : nothing}
        </div>
        ${canSubmit
          ? html`<button class="button accent small-button add-reading" @click=${this._openReading}>
              <ha-icon icon="mdi:counter"></ha-icon>${t(hass, "add_reading")}
            </button>`
          : nothing}
      </div>
      <dl class="facts">
        ${data.cost !== undefined
          ? html`<dt>${t(hass, "cost_per_m3")}</dt><dd>${formatMoney(hass, data.cost)}</dd>`
          : nothing}
        ${data.invoiceM3 !== undefined
          ? html`<dt>${t(hass, "last_invoice_usage")}</dt>
              <dd>
                ${data.invoiceKwh !== undefined
                  ? t(hass, "usage_kwh", {
                      m3: formatVolume(hass, data.invoiceM3),
                      kwh: formatNumber(hass, data.invoiceKwh),
                    })
                  : formatVolume(hass, data.invoiceM3)}
              </dd>`
          : nothing}
        ${data.estimate !== undefined
          ? html`<dt class="clickable" @click=${() => this._moreInfo(ENTITY.billEstimate)}>${t(hass, "estimate")}</dt>
              <dd class="strong">${this._money(data.estimate)}</dd>`
          : nothing}
      </dl>
      ${this._cfg.usage.show_estimate_parts && data.estimateParts.length
        ? html`<div class="parts" title=${t(hass, "estimate_hint")}>
            ${data.estimateParts.map(
              (part) => html`<div class="part">
                <span>${part.description}</span><span class="part-amount">${this._money(part.gross)}</span>
              </div>`,
            )}
          </div>`
        : nothing}
    </div>`;
  }

  // --- Account ---------------------------------------------------------------------

  private _renderAccount(data: Snapshot): TemplateResult {
    const hass = this._hass!;
    return html`<dl class="facts account">
      ${data.balance !== undefined
        ? html`<dt>${t(hass, "balance")}</dt><dd class="strong">${this._money(data.balance)}</dd>`
        : nothing}
      ${data.lastPayment !== undefined
        ? html`<dt>${t(hass, "last_payment")}</dt>
            <dd>${this._money(data.lastPayment)}${data.lastPaymentDate ? ` · ${formatDate(hass, data.lastPaymentDate)}` : ""}</dd>`
        : nothing}
      ${data.tariff ? html`<dt>${t(hass, "tariff")}</dt><dd>${data.tariff}</dd>` : nothing}
      ${data.agreement
        ? html`<dt>${t(hass, "agreement")}</dt>
            <dd>
              ${data.agreement}${data.agreementStart ? ` · ${t(hass, "since", { date: formatDate(hass, data.agreementStart) })}` : ""}
            </dd>`
        : nothing}
    </dl>`;
  }

  // --- Counters --------------------------------------------------------------------

  private _renderStats(data: Snapshot) {
    const chips = this._cfg.stats.map((key) => this._renderStat(key, data)).filter((chip) => chip !== nothing);
    return chips.length ? html`<div class="chips">${chips}</div>` : nothing;
  }

  private _renderStat(key: string, data: Snapshot): TemplateResult | typeof nothing {
    const hass = this._hass!;
    const def = STATS[key];
    if (!def || !this._stateObj(def.entity)) return nothing;
    let active = false;
    let text = "—";
    let color = def.color === "accent" ? "var(--rgb-accent)" : rgb(def.color);
    switch (key) {
      case "to_pay": {
        const { payment } = data;
        active = payment.kind === "to_pay" || payment.kind === "overdue";
        text = this._money(active ? payment.amount : 0);
        if (payment.kind === "overdue") color = "var(--rgb-red)";
        break;
      }
      case "due": {
        const due = data.payment.kind === "to_pay" ? data.payment.due : undefined;
        if (due) {
          active = true;
          text = this._when(due);
        }
        break;
      }
      case "reading":
        if (data.reading !== undefined) {
          active = true;
          text = formatVolume(hass, data.reading);
        }
        break;
      case "estimate":
        if (data.estimate !== undefined) {
          active = true;
          text = this._money(data.estimate);
        }
        break;
      case "cost":
        if (data.cost !== undefined) {
          active = true;
          text = formatMoney(hass, data.cost);
        }
        break;
      case "balance":
        if (data.balance !== undefined) {
          active = data.balance !== 0;
          text = this._money(data.balance);
        }
        break;
      case "last_payment":
        if (data.lastPayment !== undefined) {
          active = true;
          text = this._money(data.lastPayment);
        }
        break;
    }
    const title = `${t(hass, `stat_${key}` as StringKey)}: ${text}`;
    return html`<button
      class="chip"
      style=${active ? `--c: ${color}` : ""}
      title=${title}
      aria-label=${title}
      @click=${() => this._moreInfo(def.entity)}
    >
      <ha-icon .icon=${def.icon}></ha-icon><span>${text}</span>
    </button>`;
  }

  // --- Reading dialog --------------------------------------------------------------

  private _renderReadingDialog(data: Snapshot): TemplateResult | typeof nothing {
    const form = this._reading;
    if (!form) return nothing;
    const hass = this._hass!;
    const last = data.reading;
    const check = checkReading(form.value, last);
    const invalid = !check.ok && check.reason === "invalid";
    const lower = check.ok && check.lower;
    const large = check.ok && check.large;
    const ready =
      check.ok && (!lower || form.reset) && (!large || form.large) && form.confirmed && !this._busy;
    const update = (patch: Partial<ReadingForm>) => (this._reading = { ...form, ...patch, error: undefined });
    return html`<dialog class="sheet" @cancel=${(ev: Event) => (ev.preventDefault(), this._closeReading())}>
      <form @submit=${(ev: Event) => this._submitReading(ev, last)}>
        <h2>${t(hass, "reading_title")}</h2>
        ${last !== undefined
          ? html`<span class="muted note-text"
              >${t(hass, "reading_last", {
                value: formatVolume(hass, last),
                date: formatDate(hass, data.readingDate),
              })}</span
            >`
          : nothing}
        <label class="field">
          ${t(hass, "reading_value")}
          <input
            type="text"
            inputmode="decimal"
            autocomplete="off"
            .value=${form.value}
            aria-invalid=${invalid || lower ? "true" : "false"}
            @input=${(ev: InputEvent) => update({ value: (ev.target as HTMLInputElement).value })}
          />
        </label>
        <span class="field-error"
          >${invalid ? t(hass, "reading_invalid") : lower ? t(hass, "reading_lower") : large
            ? t(hass, "reading_large", { limit: MAX_READING_INCREASE_M3 })
            : ""}</span
        >
        <label class="field">
          ${t(hass, "reading_date")}
          <input
            type="date"
            .value=${form.date}
            max=${this._today()}
            @input=${(ev: InputEvent) => update({ date: (ev.target as HTMLInputElement).value })}
          />
        </label>
        ${lower
          ? html`<label class="check"
              ><input type="checkbox" .checked=${form.reset} @change=${(ev: Event) => update({ reset: (ev.target as HTMLInputElement).checked })} />${t(
                hass,
                "reading_meter_reset",
              )}</label
            >`
          : nothing}
        ${large
          ? html`<label class="check"
              ><input type="checkbox" .checked=${form.large} @change=${(ev: Event) => update({ large: (ev.target as HTMLInputElement).checked })} />${t(
                hass,
                "reading_confirm_large",
              )}</label
            >`
          : nothing}
        <div class="banner warning" style="--c: var(--rgb-amber)">
          <div class="shape"><ha-icon icon="mdi:alert-outline"></ha-icon></div>
          <span class="warning-text">${t(hass, "reading_warning")}</span>
        </div>
        <label class="check"
          ><input
            type="checkbox"
            .checked=${form.confirmed}
            @change=${(ev: Event) => update({ confirmed: (ev.target as HTMLInputElement).checked })}
          />${t(hass, "reading_confirm")}</label
        >
        ${form.error ? html`<div class="message error">${form.error}</div>` : nothing}
        <div class="actions sheet-actions">
          <button type="button" class="button" @click=${this._closeReading} ?disabled=${this._busy}>${t(hass, "cancel")}</button>
          <button type="submit" class="button filled" ?disabled=${!ready}>
            ${this._busy ? html`<ha-icon icon="mdi:loading" class="spin"></ha-icon>` : nothing}${t(hass, "reading_submit")}
          </button>
        </div>
      </form>
    </dialog>`;
  }

  static override styles = [
    baseStyles,
    css`
      :host([square]) {
        --icon-border-radius: var(--mush-icon-border-radius, 12px);
      }
      :host([dense]) {
        --spacing: var(--mush-spacing, 8px);
        --icon-size: var(--mush-icon-size, 32px);
        --control-height: var(--mush-control-height, 36px);
        --chip-height: var(--mush-chip-height, 30px);
      }
      .header .info {
        border-radius: 8px;
      }
      .body {
        display: flex;
        flex-direction: column;
        gap: var(--spacing);
        padding-bottom: var(--spacing);
      }
      .body.headless {
        padding-top: var(--spacing);
      }
      .pad {
        padding: 0 var(--spacing);
      }
      .section.titled {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .section.titled:not(:first-child) {
        padding-top: var(--spacing);
        border-top: 1px solid var(--divider-color);
      }
      .caption {
        display: flex;
        align-items: center;
        gap: 6px;
        min-height: 24px;
        padding: 0 var(--spacing);
        font-size: 11px;
        line-height: 16px;
        color: var(--secondary-text-color);
      }
      .caption-title {
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .caption-detail::before {
        content: "· ";
      }
      .alerts {
        display: flex;
        flex-direction: column;
        gap: calc(var(--spacing) / 2);
      }
      .small-button {
        flex: none;
        height: 36px;
        padding: 0 14px;
      }
      .empty {
        padding: 4px 0;
        font-size: var(--card-secondary-font-size);
        color: var(--secondary-text-color);
      }
      .note-text {
        font-size: var(--card-secondary-font-size);
      }
      .strong {
        font-weight: 600;
      }

      /* Status pill */
      .pill {
        flex: none;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 600;
        line-height: 16px;
        white-space: nowrap;
        color: rgb(var(--c));
        background-color: rgba(var(--c), 0.15);
      }

      /* Payment */
      .hero {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 2px 0;
      }
      .hero-head {
        display: flex;
        align-items: center;
        gap: 10px;
        border-radius: 8px;
      }
      .hero-value {
        font-size: 28px;
        font-weight: 700;
        line-height: 34px;
        letter-spacing: -0.01em;
        color: rgb(var(--c));
        font-variant-numeric: tabular-nums;
      }
      .hero-line {
        font-size: var(--card-secondary-font-size);
        line-height: 18px;
        color: var(--secondary-text-color);
      }
      .hero-actions {
        display: flex;
        padding-top: 6px;
      }

      /* Invoices */
      .rows {
        display: flex;
        flex-direction: column;
        margin: 0 calc(var(--spacing) / -2);
      }
      .row-item {
        padding: 6px calc(var(--spacing) / 2);
        border-radius: var(--control-border-radius);
      }
      .row-item.clickable:hover {
        background-color: var(--tint);
      }
      .shape.small {
        --icon-size: 32px;
      }
      .shape.large {
        --icon-size: 48px;
      }

      /* Usage */
      .usage {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 2px 0;
      }
      .usage-row {
        display: flex;
        align-items: center;
        gap: var(--spacing);
      }
      .usage-head {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        border-radius: 8px;
      }
      .usage-value {
        font-size: 28px;
        font-weight: 700;
        line-height: 34px;
        color: rgb(var(--c));
        font-variant-numeric: tabular-nums;
      }
      .usage-value small {
        margin-inline-start: 3px;
        font-size: 14px;
        font-weight: 600;
      }
      .usage-line {
        font-size: var(--card-secondary-font-size);
        line-height: var(--card-secondary-line-height);
        color: var(--secondary-text-color);
      }
      .facts {
        line-height: 20px;
      }
      .facts dd {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      .parts {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 6px 10px;
        border-radius: var(--control-border-radius);
        background-color: var(--tint);
        font-size: var(--card-secondary-font-size);
        line-height: 18px;
      }
      .part {
        display: flex;
        gap: 8px;
        justify-content: space-between;
        color: var(--secondary-text-color);
      }
      .part-amount {
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
      }

      /* Reading dialog */
      .banner.warning {
        align-items: center;
      }
      .warning-text {
        font-size: var(--card-secondary-font-size);
        line-height: 18px;
        color: var(--primary-text-color);
      }
      .sheet-actions {
        padding: 4px 0 0;
      }
      .spin {
        animation: spin 1s linear infinite;
      }
      @keyframes spin {
        to {
          transform: rotate(360deg);
        }
      }

      /* Layouts */
      ha-card.compact {
        justify-content: center;
      }
      .compact .state-item {
        height: 100%;
        box-sizing: border-box;
      }
      :host([layout="grid"]) .compact .state-item {
        padding-block: 0;
      }
      .compact-amount {
        flex: none;
        font-size: var(--card-primary-font-size);
        font-weight: 700;
        color: rgb(var(--c));
        font-variant-numeric: tabular-nums;
      }
      ha-card.tile {
        align-items: center;
        justify-content: center;
        gap: 4px;
        padding: var(--spacing);
        text-align: center;
      }
      ha-card.tile .primary,
      ha-card.tile .secondary {
        max-width: 100%;
      }
      ha-card.tile .shape {
        margin-bottom: 6px;
      }
    `,
  ];
}
