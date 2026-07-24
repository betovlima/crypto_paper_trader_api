import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const header = read("src", "components", "layout", "DashboardHeader.jsx");
const adaptive = read("src", "features", "adaptive-research", "AdaptiveResearchPanel.jsx");
const strategy = read("src", "features", "strategies", "StrategyCard.jsx");

for (const field of ["market_label", "decision_timeframe_label", "trend_timeframe_label", "next_analysis_at", "last_market_update_label"]) {
  if (!header.includes(field)) throw new Error(`Header field missing: ${field}`);
}
for (const field of ["best_candidate", "tested_count", "approved_count", "pattern_analysis", "entry_trigger_price", "potential_target_price"]) {
  if (!adaptive.includes(field)) throw new Error(`Adaptive selector field missing: ${field}`);
}
if (!strategy.includes("<AdaptiveResearchPanel")) throw new Error("Adaptive panel is not rendered by StrategyCard.");
console.log("Frontend boundaries: header, adaptive research and strategy card remain server-data driven.");
