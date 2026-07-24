import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, "..");
const sourceRoot = path.join(projectRoot, "src");
const i18nPath = path.join(sourceRoot, "i18n.js");

function listSourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return listSourceFiles(fullPath);
    if (!/\.(js|jsx)$/.test(entry.name) || fullPath === i18nPath) return [];
    return [fullPath];
  });
}

const originalI18n = fs.readFileSync(i18nPath, "utf8");
const executableI18n = originalI18n
  .replace(/\bexport\s+const\s+/g, "const ")
  .replace(/\bexport\s+function\s+/g, "function ")
  + "\nglobalThis.__translationDictionaries = dictionaries;\n";

const context = {};
vm.runInNewContext(executableI18n, context, { filename: i18nPath });

const dictionaries = context.__translationDictionaries;
if (!dictionaries?.pt || !dictionaries?.es) {
  throw new Error("Unable to load the Portuguese and Spanish dictionaries.");
}

const literalCallPattern = /\bt\(\s*(["'])(.*?)\1\s*\)/gs;
const usedKeys = new Map();

for (const filePath of listSourceFiles(sourceRoot)) {
  const source = fs.readFileSync(filePath, "utf8");
  for (const match of source.matchAll(literalCallPattern)) {
    const key = match[2]
      .replace(/\\"/g, '"')
      .replace(/\\'/g, "'")
      .replace(/\\n/g, "\n");
    const line = source.slice(0, match.index).split("\n").length;
    const locations = usedKeys.get(key) || [];
    locations.push(`${path.relative(projectRoot, filePath)}:${line}`);
    usedKeys.set(key, locations);
  }
}

let failed = false;

for (const language of ["pt", "es"]) {
  const missing = [...usedKeys.keys()]
    .filter((key) => !Object.prototype.hasOwnProperty.call(dictionaries[language], key))
    .sort((left, right) => left.localeCompare(right));

  if (missing.length === 0) {
    console.log(`${language.toUpperCase()}: all ${usedKeys.size} literal translation keys are covered.`);
    continue;
  }

  failed = true;
  console.error(`\n${language.toUpperCase()}: ${missing.length} missing translation keys:`);
  for (const key of missing) {
    console.error(`- ${JSON.stringify(key)} (${usedKeys.get(key).join(", ")})`);
  }
}

if (failed) process.exit(1);
