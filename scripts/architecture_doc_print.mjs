// Prints the assembled architecture document HTML to PDF through headless Chromium.
//
// Run by `scripts/architecture_doc.py build` as `npx -p @mermaid-js/mermaid-cli@<pinned> node <this> <job.json>`, so it
// uses the Puppeteer (and the Chromium) bundled with mermaid-cli: no other browser or PDF tool is installed. npx puts
// mermaid-cli's `node_modules/.bin` on PATH; Puppeteer is resolved from the `node_modules` beside it.
//
// job.json: {"html": "<path>", "pdf": "<path>", "footer": "<text>", "args": ["--no-sandbox"]}

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const job = JSON.parse(readFileSync(process.argv[2], "utf8"));

const bin = process.env.PATH.split(path.delimiter).find((dir) => existsSync(path.join(dir, "mmdc")));
if (!bin) throw new Error("mermaid-cli is not on PATH: run this through `npx -p @mermaid-js/mermaid-cli`");
const require = createRequire(path.join(bin, "..", "resolve-from-here.js"));
const { default: puppeteer } = await import(pathToFileURL(require.resolve("puppeteer")).href);

const escape = (text) => text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const footer = `<div style="font-family: Helvetica, Arial, sans-serif; font-size: 7.5pt; color: #555; width: 100%; margin: 0 18mm;
  display: flex; justify-content: space-between"><span>${escape(job.footer)}</span>
  <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>`;

const browser = await puppeteer.launch({ args: job.args });
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(job.html).href, { waitUntil: "load" });
  await page.pdf({
    path: job.pdf,
    format: "A4",
    preferCSSPageSize: true,
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: "<span></span>",
    footerTemplate: footer,
    outline: true, // PDF bookmarks from the headings
    tagged: true,
  });
} finally {
  await browser.close();
}
