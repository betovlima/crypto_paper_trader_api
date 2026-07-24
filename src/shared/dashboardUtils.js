import { INTL_LOCALES } from "../i18n";
import {
  MARKET_QUOTE_ASSETS,
  PINNED_STRATEGY_CODE,
  STRATEGY_LABELS,
  STRATEGY_ORDER_STORAGE_KEY,
} from "../config/dashboard";

export function readStoredStrategyOrder() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STRATEGY_ORDER_STORAGE_KEY) || "[]");
    return Array.isArray(stored) ? stored.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function parseApiDate(value) {
  if (!value) return null;
  if (typeof value === "number") {
    const numericDate = new Date(value);
    return Number.isNaN(numericDate.getTime()) ? null : numericDate;
  }
  const text = String(value);
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const date = new Date(hasTimezone ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatNumber(value, digits = 2, language = "en") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat(INTL_LOCALES[language] || "en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

export function formatPrice(value, language = "en") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const absolute = Math.abs(Number(value));
  const digits = absolute >= 1000 ? 2 : absolute >= 1 ? 5 : 8;
  return formatNumber(value, digits, language);
}

export function formatPercent(value, digits = 2, language = "en") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${formatNumber(Number(value) * 100, digits, language)}%`;
}

export function formatSignedMoney(value, language = "en") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const numeric = Number(value);
  return `${numeric >= 0 ? "+" : ""}${formatNumber(numeric, 2, language)} USDT`;
}


export function formatTime(value, language = "en") {
  const date = parseApiDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat(INTL_LOCALES[language] || "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTime(value, language = "en") {
  const date = parseApiDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat(INTL_LOCALES[language] || "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date);
}

export function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds)) return "—";
  const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  if (hours > 0) return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function normalizeMarketSymbol(value) {
  return String(value || "")
    .toUpperCase()
    .replace(/[\s/_:-]+/g, "")
    .trim();
}

export function formatMarketPair(value) {
  const normalized = normalizeMarketSymbol(value);
  if (!normalized) return "";
  const quoteAsset = MARKET_QUOTE_ASSETS.find(
    (quote) => normalized.endsWith(quote) && normalized.length > quote.length,
  );
  if (!quoteAsset) return normalized;
  return `${normalized.slice(0, -quoteAsset.length)}/${quoteAsset}`;
}

export function sameRecord(previous, next) {
  if (previous === next) return true;
  if (!previous || !next) return previous === next;
  return JSON.stringify(previous) === JSON.stringify(next);
}

export function sameRows(previous, next) {
  if (previous === next) return true;
  if (!Array.isArray(previous) || !Array.isArray(next)) return false;
  if (previous.length !== next.length) return false;
  return previous.every((item, index) => sameRecord(item, next[index]));
}

export function setStable(setter, next, comparator = sameRecord) {
  setter((previous) => (comparator(previous, next) ? previous : next));
}

export function statusLabel(status, t = (value) => value) {
  return t({
    RUNNING: "Running",
    STOP_REQUESTED: "Stopping",
    FINISHED: "Finished",
    MANUALLY_STOPPED: "Stopped",
    STOPPED: "Stopped",
    FAILED: "Failed",
    ACTIVE: "Active",
  }[status] || status || "Unknown");
}

export function strategyName(strategy, t = (value) => value) {
  if (!strategy) return "—";
  return t(STRATEGY_LABELS[strategy.strategy_code] || strategy.display_name || strategy.strategy_code);
}

export function strategyRuntimeStatus(strategy, t = (value) => value) {
  if (!strategy) return t("Waiting");
  if (strategy.setup_status === "EXIT_ARMED") return t("Exit armed");
  if (strategy.has_open_position) return t("In position");
  if (strategy.strategy_code === "AI_PATTERN_TRADER") {
    if (strategy.ai_risk_status === "LEARNING") return t("Learning");
    if (strategy.ai_risk_status === "BLOCKED") return t("Risk blocked");
    return t("Monitoring");
  }
  if (strategy.setup_status === "ARMED") return t("Setup armed");
  return t("Monitoring");
}

export function decisionSignal(decision) {
  return String(decision?.final_signal || decision?.ai_proposed_action || "HOLD").toUpperCase();
}

export function strategyAutomationState(strategy, decision, t = (value) => value) {
  const signal = decisionSignal(decision);

  if (strategy?.has_open_position) {
    return {
      label: t("ACTIVE POSITION"),
      tone: "active",
      title: t("Position open. Risk controls are active."),
    };
  }

  if (signal === "BUY") {
    return {
      label: t("ENTERING MARKET"),
      tone: "buy",
      title: t("Buy signal confirmed."),
    };
  }

  if (signal === "SELL") {
    return {
      label: t("EXITING MARKET"),
      tone: "sell",
      title: t("Exit signal confirmed."),
    };
  }

  if (strategy?.setup_status === "ARMED") {
    return {
      label: t("ENTRY ARMED"),
      tone: "armed",
      title: t("Setup ready. Waiting for entry."),
    };
  }

  return {
    label: t("WAITING"),
    tone: "waiting",
    title: t("No action on this candle."),
  };
}

export function strategyAutomaticPriority(strategy, decision) {
  if (strategy?.strategy_code === PINNED_STRATEGY_CODE) return 0;

  const signal = decisionSignal(decision);

  // A strategy with capital exposed must always be the first operational card.
  if (strategy?.has_open_position) return 10;

  // Transitional states are ordered by how close they are to changing exposure.
  if (signal === "SELL") return 20;
  if (strategy?.setup_status === "EXIT_ARMED") return 30;
  if (signal === "BUY") return 40;
  if (strategy?.setup_status === "ARMED") return 50;

  // AI-specific states appear after actionable trading states.
  if (strategy?.ai_risk_status === "BLOCKED") return 60;
  if (strategy?.ai_risk_status === "LEARNING") return 70;

  return 80;
}

export function strategyOpenPositionUrgency(strategy, decision, marketPrice) {
  if (!strategy?.has_open_position) return null;

  const signal = decisionSignal(decision);
  const exitAttention = signal === "SELL"
    ? 0
    : strategy?.setup_status === "EXIT_ARMED"
      ? 1
      : 2;

  const entryPrice = Number(
    strategy?.entry_execution_price
      || strategy?.average_entry_price
      || strategy?.entry_market_price
      || 0,
  );
  const currentPrice = Number(marketPrice || 0);
  const openReturn = entryPrice > 0 && currentPrice > 0
    ? (currentPrice - entryPrice) / entryPrice
    : 0;

  const entryTimestamp = Date.parse(
    strategy?.entry_candle_timestamp
      || strategy?.entry_time
      || "",
  );

  return {
    exitAttention,
    openReturn,
    entryTimestamp: Number.isFinite(entryTimestamp)
      ? entryTimestamp
      : Number.MAX_SAFE_INTEGER,
  };
}

export function selectedStrategyLabel(strategy, decision, t = (value) => value) {
  if (strategy?.strategy_code !== "ADAPTIVE_STRATEGY_SELECTOR") return null;

  const activeName = (
    strategy?.selector_active_strategy_name
    || decision?.selector_active_strategy_name
    || null
  );
  if (activeName) return activeName;

  const selectedCode = (
    strategy?.selector_selected_strategy
    || decision?.selector_selected_strategy
    || null
  );
  if (!selectedCode || selectedCode === "UNDEFINED") return t("No validated strategy yet");
  return selectedCode;
}

export function parseStringArray(value) {
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string");
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function parseJsonObject(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : {};
  } catch {
    return {};
  }
}

export function sourceLabel(value) {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return value;
  }
}

export function pnlTone(value) {
  const numeric = Number(value || 0);
  if (numeric > 0) return "positive";
  if (numeric < 0) return "negative";
  return "neutral";
}

