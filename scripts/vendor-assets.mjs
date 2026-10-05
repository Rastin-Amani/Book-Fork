// Copies runtime JS from node_modules into static/js/vendor so the app is
// self-hosted (no CDN, works offline, production-safe).
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = resolve(root, "static/js/vendor");
mkdirSync(outDir, { recursive: true });

const assets = [
  ["node_modules/htmx.org/dist/htmx.min.js", "static/js/vendor/htmx.min.js"],
  ["node_modules/alpinejs/dist/cdn.min.js", "static/js/vendor/alpine.min.js"],
];

for (const [from, to] of assets) {
  const src = resolve(root, from);
  const dest = resolve(root, to);
  copyFileSync(src, dest);
  console.log(`vendored ${to}`);
}
