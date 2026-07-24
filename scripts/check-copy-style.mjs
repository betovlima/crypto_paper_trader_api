import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = [
  "src/App.jsx",
  "src/i18n.js",
  "src/components/layout/DashboardHeader.jsx",
  "src/features/adaptive-research/AdaptiveResearchPanel.jsx",
  "src/features/strategies/StrategyCard.jsx",
];
const source = files.map((file) => fs.readFileSync(path.join(root, file), "utf8")).join("\n");
const forbidden = ["Selected asset only", "One decision clock for every strategy", "Analysis scope", "Same closed-candle cycle as every strategy"];
const violations = forbidden.filter((text) => source.includes(text));
if (violations.length) throw new Error(`Redundant UI copy remains: ${violations.join(" | ")}`);
console.log("Copy style: primary interface remains concise.");
