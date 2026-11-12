import { makeHass } from "./stubs.js";

const THEMES = {
  light: { "--primary-text-color": "#141414", "--secondary-text-color": "#5e5e5e", "--rgb-primary-text-color": "20, 20, 20",
    "--card-background-color": "#ffffff", "--primary-background-color": "#f5f5f5", "--divider-color": "rgba(0,0,0,.12)",
    "--primary-color": "#009ac7", "--rgb-primary-color": "0, 154, 199", "background": "#f5f5f5", "color": "#141414" },
  dark: { "--primary-text-color": "#e1e1e1", "--secondary-text-color": "#9b9b9b", "--rgb-primary-text-color": "225, 225, 225",
    "--card-background-color": "#1c1c1c", "--primary-background-color": "#111111", "--divider-color": "rgba(225,225,225,.12)",
    "--primary-color": "#009ac7", "--rgb-primary-color": "0, 154, 199", "background": "#111111", "color": "#e1e1e1" },
};

const params = new URLSearchParams(location.search);
const language = params.get("lang") ?? "pl";
const scenario = params.get("scenario") ?? "main";
const only = params.get("theme");

const ALL = ["alerts", "payment", "invoices", "usage", "account", "stats"];
const ALL_STATS = ["to_pay", "due", "reading", "estimate", "cost", "balance", "last_payment"];
// [config, makeHass options, width]
const SCENARIOS = {
  main: [[{}, {}, 440]],
  everything: [[{ sections: ALL, stats: ALL_STATS }, {}, 440]],
  states: [
    [{ sections: ["alerts", "payment"] }, { scenario: "to_pay" }, 400],
    [{ sections: ["alerts", "payment"] }, { scenario: "overdue", notice: false }, 400],
    [{ sections: ["alerts", "payment"] }, { scenario: "paid", notice: false }, 400],
    [{}, { offline: true }, 400],
  ],
  layouts: [
    [{ layout: "compact" }, { scenario: "to_pay" }, 380],
    [{ layout: "compact", header_info: "reading", accent_color: "blue" }, {}, 380],
    [{ layout: "tile" }, { scenario: "overdue" }, 180],
    [{ show_header: false, sections: ["usage", "stats"], density: "dense", icon_shape: "square" }, {}, 380],
  ],
  reading: [[{ sections: ["usage"] }, {}, 440]],
};

const single = only && THEMES[only];
document.documentElement.style.background = single ? THEMES[only].background : "";
document.body.style.cssText = "margin:0;display:flex;width:fit-content;font-family:Roboto,'Noto Sans',system-ui,sans-serif;font-size:14px";
for (const [theme, vars] of Object.entries(THEMES)) {
  if (single && theme !== only) continue;
  const col = document.createElement("div");
  col.style.cssText = "padding:16px;display:flex;flex-direction:column;gap:16px;align-items:flex-start";
  for (const [k, v] of Object.entries(vars)) col.style.setProperty(k, v);
  document.body.append(col);
  for (const [config, options, width] of SCENARIOS[scenario]) {
    const wrap = document.createElement("div");
    wrap.style.width = `${width}px`;
    const card = document.createElement("myorlen-ebok-card");
    card.setConfig({ type: "custom:myorlen-ebok-card", device_id: "meter1", ...config });
    wrap.append(card);
    col.append(wrap);
    card.hass = makeHass({ language, dark: theme === "dark", ...options });
    card.addEventListener("hass-notification", (ev) => console.log("toast", ev.detail.message));
  }
}
