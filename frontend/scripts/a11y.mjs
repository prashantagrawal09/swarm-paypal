// Accessibility audit: runs axe-core (WCAG 2.1 A/AA and best practices) over every page,
// its overlays and a phone-sized window, in light and dark.
//
//   npm run a11y            # needs the API on :8000, the web app on :3000 and a week run
//
// Uses the Chrome already on this machine (CHROME_PATH overrides where to find it).
// Exits 1 if anything is found.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://localhost:8000";
const CHROME =
  process.env.CHROME_PATH ??
  [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
  ].find((candidate) => fs.existsSync(candidate));
if (!CHROME) {
  console.error("Chrome not found. Set CHROME_PATH to a Chrome or Chromium binary.");
  process.exit(2);
}

const here = path.dirname(fileURLToPath(import.meta.url));
const axeSource = fs.readFileSync(path.join(here, "../node_modules/axe-core/axe.min.js"), "utf8");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let orderId = "none";
try {
  const orders = await (await fetch(`${API}/api/group-orders`)).json();
  orderId = (orders.find((order) => order.category === "DAIRY") ?? orders[0])?.id ?? "none";
} catch {
  console.error(`The API isn't answering at ${API}. Start it (make backend) and run a week first.`);
  process.exit(2);
}

/** Each case: a page, optionally something to do on it first, optionally a phone-sized window. */
const cases = [
  { name: "home", path: "/" },
  { name: "watch", path: "/watch", act: () => wait(5000) },
  { name: "live board", path: "/live" },
  { name: "shops", path: "/shops" },
  { name: "shop", path: "/shop/cafe-mei" },
  { name: "suppliers", path: "/suppliers" },
  { name: "supplier", path: "/supplier/johorfarm" },
  { name: "group order", path: `/orders/${orderId}` },
  { name: "money", path: "/money" },
  { name: "demo panel", path: "/demo" },
  { name: "connect PayPal", path: "/connect/cafe-mei" },
  {
    name: "inspector open",
    path: `/orders/${orderId}`,
    act: async (page) => {
      await page.evaluate(() => {
        const buttons = [...document.querySelectorAll("button")].filter((button) =>
          button.textContent.includes("How was this decided"),
        );
        buttons[buttons.length - 1]?.click();
      });
      await wait(1200);
    },
  },
  {
    name: "command palette open",
    path: "/shops",
    act: async (page) => {
      await page.keyboard.down("Control");
      await page.keyboard.press("k");
      await page.keyboard.up("Control");
      await wait(900);
    },
  },
  {
    name: "watch: the week's summary",
    path: "/watch",
    act: async (page) => {
      await wait(1500);
      for (let day = 0; day < 9; day++) {
        await page.keyboard.press("ArrowRight");
        await wait(250);
      }
      await wait(2500);
    },
  },
  {
    name: "watch: shortcut list",
    path: "/watch",
    act: async (page) => {
      await wait(1500);
      await page.keyboard.press("?");
      await wait(700);
    },
  },
  { name: "home (phone)", path: "/", width: 390 },
  { name: "live board (phone)", path: "/live", width: 390 },
  { name: "shop (phone)", path: "/shop/cafe-mei", width: 390 },
  { name: "watch (phone)", path: "/watch", width: 390, act: () => wait(5000) },
  { name: "money (phone)", path: "/money", width: 390 },
  { name: "demo panel (phone)", path: "/demo", width: 390 },
];

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), "swarm-a11y-")),
  args: ["--no-first-run", "--hide-scrollbars"],
});

let found = 0;
try {
  for (const item of cases) {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage();
      const width = item.width ?? 1440;
      await page.setViewport({ width, height: 900, isMobile: width < 500, hasTouch: width < 500 });
      // Reduced motion, so nothing is measured half-way through fading in.
      await page.emulateMediaFeatures([
        { name: "prefers-color-scheme", value: theme },
        { name: "prefers-reduced-motion", value: "reduce" },
      ]);
      await page.evaluateOnNewDocument(
        (value) => localStorage.setItem("swarm-theme", value),
        theme,
      );
      await page.goto(WEB + item.path, { waitUntil: "domcontentloaded" });
      // The framework's own development badge is not part of the site.
      await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
      await wait(4000);
      if (item.act) await item.act(page);
      await page.evaluate(axeSource);
      const violations = await page.evaluate(async () => {
        const result = await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa", "best-practice"] },
        });
        return result.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.slice(0, 3).map((node) => ({
            target: node.target.join(" "),
            why: (node.any[0] ?? node.all[0] ?? node.none[0])?.message ?? "",
          })),
          count: violation.nodes.length,
        }));
      });
      const label = `${item.name}, ${theme}`;
      if (violations.length === 0) {
        console.log(`ok    ${label}`);
      } else {
        for (const violation of violations) {
          found += violation.count;
          console.log(`FAIL  ${label}: [${violation.impact}] ${violation.id} x${violation.count}`);
          console.log(`      ${violation.help}`);
          for (const node of violation.nodes)
            console.log(`      - ${node.target}\n        ${node.why}`);
        }
      }
      await page.close();
    }
  }
} finally {
  await browser.close();
}

console.log(found === 0 ? "\nNo accessibility problems found." : `\n${found} problem(s) found.`);
process.exit(found === 0 ? 0 : 1);
