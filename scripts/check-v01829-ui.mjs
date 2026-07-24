import fs from "node:fs";

const app = fs.readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const card = fs.readFileSync(new URL("../src/features/strategies/StrategyCard.jsx", import.meta.url), "utf8");
const adaptive = fs.readFileSync(new URL("../src/features/adaptive-research/AdaptiveResearchPanel.jsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../src/styles/dashboard.css", import.meta.url), "utf8");

const checks = [
  [!app.includes('{strategies.length} {t("strategies")}'), "redundant strategy heading summary removed"],
  [card.includes("strategy-hint-preview"), "strategy hint preview present"],
  [adaptive.includes("AdaptiveResearchCountdownRing"), "adaptive research countdown component present"],
  [adaptive.includes("selector_next_research_at"), "adaptive research schedule drives the countdown"],
  [css.includes("width: 102px"), "compact spinner size present"],
  [app.includes("REFRESH_SECONDS * 1000"), "20-second dashboard refresh remains active in the background"],
  [!adaptive.includes("Data refresh every 20 seconds"), "dashboard refresh is not shown in the spinner"],
];

for (const [ok, label] of checks) {
  if (!ok) throw new Error(`UI check failed: ${label}`);
}

console.log("v0.18.29 UI checks passed.");
