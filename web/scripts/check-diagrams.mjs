// Parse-check every Mermaid diagram in a directory tree with the real Mermaid
// parser, so a broken diagram is caught before it reaches a reader.
//
//   npm run diagrams              (from web/)
//   python run.py diagrams        (from the repo root)
//
// It lives under web/ rather than the repo's scripts/ because Node resolves
// node_modules by walking up from the importing file, and web/ is the only
// place in this repository with an npm install.
//
// Files are normalised to LF first: committed Markdown is checked out with CRLF
// on Windows, and a fence regex anchored on "\n" silently matches nothing there
// — which looks exactly like "no diagrams to check".
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
});
for (const k of [
  "window", "document", "Element", "SVGElement", "HTMLElement", "Node",
  "getComputedStyle", "DOMPurify",
]) {
  if (dom.window[k] !== undefined) {
    try {
      Object.defineProperty(globalThis, k, {
        value: dom.window[k], configurable: true, writable: true,
      });
    } catch {
      /* node 22 makes a few globals getter-only; skip those */
    }
  }
}

const mermaid = (await import("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

const FENCE = /^```mermaid$/;

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.name.endsWith(".md")) out.push(full);
  }
  return out;
}

function extract(file) {
  const lines = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let open = null;
  for (const line of lines) {
    if (open === null) {
      if (FENCE.test(line.trim())) open = [];
    } else if (line.trim() === "```") {
      blocks.push(open.join("\n"));
      open = null;
    } else {
      open.push(line);
    }
  }
  return blocks;
}

const roots = process.argv.slice(2);
const files = roots.flatMap(walk);
let total = 0;
let bad = 0;

for (const file of files) {
  const blocks = extract(file);
  for (const [i, code] of blocks.entries()) {
    total++;
    try {
      await mermaid.parse(code);
    } catch (e) {
      bad++;
      const msg = String(e?.message ?? e).split("\n").slice(0, 2).join(" | ");
      console.log(`FAIL ${path.relative(process.cwd(), file)} #${i + 1}: ${msg}`);
    }
  }
}

console.log(`checked ${total} mermaid blocks across ${files.length} markdown files`);
console.log(bad ? `${bad} FAILED` : "ALL DIAGRAMS PARSE");
process.exit(bad ? 1 : 0);
