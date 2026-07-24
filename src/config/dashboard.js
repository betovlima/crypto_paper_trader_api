export const APP_VERSION = __APP_VERSION__;
export const SELECTED_EXPERIMENT_STORAGE_KEY = "crypto-paper-trader-selected-experiment";
export const LANGUAGE_STORAGE_KEY = "crypto-paper-trader-language";
export const STRATEGY_ORDER_STORAGE_KEY = "crypto-paper-trader-strategy-card-order";
export const REFRESH_SECONDS = 20;
export const AI_SCANNER_REFRESH_MS = 2000;
export const AI_OPPORTUNITY_CARD_LIMIT = 10;
export const PINNED_STRATEGY_CODE = "ADAPTIVE_STRATEGY_SELECTOR";
export const AI_SCANNER_DELAY_THRESHOLD_MS = 90000;

export const AI_SCANNER_PROCESSING_STATES = new Set([
  "STARTING",
  "SELECTING_MARKETS",
  "FILTERING_MARKETS",
  "DOWNLOADING_CANDLES",
  "TRAINING_MODELS",
  "RANKING_OPPORTUNITIES",
]);

export const AI_SCANNER_STATUS_MESSAGES = {
  STARTING: "Starting the AI opportunity scanner",
  SELECTING_MARKETS: "Selecting the most liquid MEXC markets",
  FILTERING_MARKETS: "Filtering pairs by liquidity, price and market quality",
  DOWNLOADING_CANDLES: "Downloading closed candles and current market depth",
  TRAINING_MODELS: "Training and validating the adaptive model",
  RANKING_OPPORTUNITIES: "Ranking the strongest entry opportunities",
  READY: "Opportunity ranking ready",
  ERROR: "The AI scanner could not complete the current scan",
  DISABLED: "The AI opportunity scanner is disabled",
  STOPPED: "The AI opportunity scanner is stopped",
};

export const STRATEGY_LABELS = {
  ADAPTIVE_STRATEGY_SELECTOR: "Adaptive Pattern Strategy",
  CURRENT_HYBRID: "Market Confirmation with AI",
  EMA_CROSSOVER_COST_AWARE: "Trend Change by Moving Averages",
  EMA_PULLBACK: "Buy After a Temporary Price Pullback",
  EMA9_SETUP_91_COST_AWARE: "EMA 9 Reversal with Breakout",
  EMA9_SETUP_91_TREND_FOLLOWER: "EMA 9 Reversal with Moving Stop",
  LARRY_VOLATILITY_BREAKOUT: "Buy When Price Breaks Its Recent Range",
  STORMER_FILHA_MAL_CRIADA: "Buy on a Pullback in an Uptrend",
  LBR_310_ANTI_CONTEXT: "Trend Resumption with LBR 3/10",
  AI_PATTERN_TRADER: "AI-Based Market Pattern Detection",
};

export const MARKET_QUOTE_ASSETS = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "BTC", "ETH", "BNB"];

export const STRATEGY_VISUALS = {
  ADAPTIVE_STRATEGY_SELECTOR: {
    accent: "#a78bfa",
    summary: "Finds recurring patterns in the asset history and tests rules for the next candle.",
    example: "It can combine moving averages, volume and candle patterns when the backtest supports the setup.",
  },
  CURRENT_HYBRID: {
    accent: "#60a5fa",
    cardDescription: "Combines trend, momentum, volume and an AI direction estimate.",
    summary: "Combines moving averages, RSI, ADX, volume and the XGBoost direction estimate.",
    example: "A buy is considered only when the main signals point in the same direction.",
  },
  EMA_CROSSOVER_COST_AWARE: {
    accent: "#38bdf8",
    cardDescription: "Confirms a possible trend change with fast and slow averages.",
    summary: "Looks for the fast average to cross above the slow average, with trend, strength and volume confirmation.",
    example: "The signal is ignored when the candle closes weak or too far from the averages.",
  },
  EMA_PULLBACK: {
    accent: "#2dd4bf",
    cardDescription: "Waits for price to return to the averages during an uptrend.",
    summary: "Waits for price to return to the moving averages during an uptrend and show strength again.",
    example: "The entry comes after a clear reaction near the averages.",
  },
  EMA9_SETUP_91_COST_AWARE: {
    accent: "#fbbf24",
    authorLabel: "Larry Williams",
    attribution: "Original setup by Larry Williams.",
    cardDescription: "Looks for an EMA 9 reversal followed by a breakout.",
    summary: "Looks for an EMA 9 reversal and a later close above the reference candle high.",
    example: "A wick above the trigger is not enough; the candle must close above it.",
  },
  EMA9_SETUP_91_TREND_FOLLOWER: {
    accent: "#fb923c",
    authorLabel: "Based on Larry Williams",
    attribution: "Application adaptation based on the Larry Williams 9.1 setup.",
    cardDescription: "Uses the EMA 9 entry and raises the stop as price advances.",
    summary: "Uses the EMA 9 reversal for entry and raises the stop as the trend advances.",
    example: "After entry, favorable candles can move the stop upward, never downward.",
  },
  LARRY_VOLATILITY_BREAKOUT: {
    accent: "#f472b6",
    authorLabel: "Larry Williams",
    attribution: "Volatility breakout method popularized by Larry Williams.",
    cardDescription: "Looks for a strong close outside the recent price range.",
    summary: "Builds a trigger from the recent range and waits for a strong close above it.",
    example: "A wick-only breakout is ignored; trend and volume must confirm the move.",
  },
  STORMER_FILHA_MAL_CRIADA: {
    accent: "#34d399",
    authorLabel: "Stormer",
    attribution: "Created by Alexandre Wolwacz, known as Stormer.",
    cardDescription: "Uses seven aligned averages to find pullbacks in an uptrend.",
    summary: "Uses seven aligned moving averages to find pullbacks inside an uptrend.",
    example: "The setup waits for price to leave the average ribbon with a confirmed close.",
  },
  LBR_310_ANTI_CONTEXT: {
    accent: "#c084fc",
    authorLabel: "Linda Bradford Raschke",
    attribution: "Based on Linda Bradford Raschke's 3/10 Anti setup.",
    cardDescription: "Looks for momentum to resume after a light pullback.",
    summary: "Looks for a light pullback after positive momentum and confirms the continuation with the LBR 3/10 oscillator.",
    example: "The setup waits for momentum to turn up and for price to close above the pullback high.",
  },
  AI_PATTERN_TRADER: {
    accent: "#818cf8",
    cardDescription: "Finds recurring candle and indicator patterns.",
    summary: "Learns combinations of candles and indicators that preceded favorable moves.",
    example: "The signal is used only when confidence and risk checks are acceptable.",
  },
};
