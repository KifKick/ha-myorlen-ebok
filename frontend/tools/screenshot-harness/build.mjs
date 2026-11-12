// Assembles out/: the built card bundle, the stubbed page and its HTML.
import { copyFileSync, mkdirSync } from "node:fs";

import * as esbuild from "esbuild";

const here = new URL(".", import.meta.url);
const out = new URL("out/", here);
mkdirSync(out, { recursive: true });
copyFileSync(new URL("index.html", here), new URL("index.html", out));
copyFileSync(
  new URL("../../../custom_components/myorlen_ebok/frontend/myorlen-ebok-card.js", here),
  new URL("myorlen-ebok-card.js", out),
);

await esbuild.build({
  entryPoints: [new URL("page.js", here).pathname],
  outfile: new URL("page.bundle.js", out).pathname,
  bundle: true,
  format: "esm",
  logLevel: "warning",
});
