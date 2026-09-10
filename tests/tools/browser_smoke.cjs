// Requires Playwright and an installed browser; no application dependencies change.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

async function main() {
  const output = process.argv[2] || "outputs/system_sanity/browser";
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.platform === "win32" ? { channel: "msedge" } : {}),
  });
  const results = [];
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(process.env.STREAMLIT_UAT_URL || "http://127.0.0.1:8501");
      await page.getByText("Connect", { exact: true }).click();
      await page.getByText("Connected registry:", { exact: false }).waitFor();
      for (const name of ["Registry", "Agent Playground", "Workflow Playground"]) {
        if (name !== "Registry") {
          await page.getByText(name, { exact: true }).first().click();
        }
        await page.getByRole("heading", { name, exact: true }).waitFor();
        await page.screenshot({ path: path.join(output, `${viewport.width}-${name.replaceAll(" ", "-")}.png`), fullPage: true });
        assert.equal(await page.getByTestId("stException").count(), 0);
        assert.equal(await page.getByTestId("stAlert").filter({ hasText: "Traceback" }).count(), 0);
      }
      await page.getByText("Registry", { exact: true }).first().click();
      await page.getByText("Disconnect", { exact: true }).click();
      await page.getByText("Registry is not connected.", { exact: true }).waitFor();
      assert.deepEqual(errors, []);
      results.push({ viewport, pages: 3, javascriptErrors: errors, disconnect: "pass" });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(output, "browser-summary.json"), JSON.stringify(results, null, 2));
  console.log("PASS: desktop/mobile Registry, Agent Playground, Workflow Playground, disconnect");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
