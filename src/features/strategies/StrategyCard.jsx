import { memo, useLayoutEffect, useRef } from "react";
import { PINNED_STRATEGY_CODE, STRATEGY_VISUALS } from "../../config/dashboard";
import { decisionSignal, formatDateTime, formatNumber, formatPercent, formatPrice, formatSignedMoney, pnlTone, selectedStrategyLabel, strategyAutomationState, strategyName } from "../../shared/dashboardUtils";
import { AdaptiveResearchPanel } from "../adaptive-research/AdaptiveResearchPanel";

const STRATEGY_TITLE_MIN_FONT_PX = 15.5;
const STRATEGY_TITLE_MAX_FONT_PX = 19;

function ResponsiveStrategyTitle({ title }) {
  const rowRef = useRef(null);
  const titleRef = useRef(null);

  useLayoutEffect(() => {
    const row = rowRef.current;
    const titleElement = titleRef.current;
    if (!row || !titleElement) return undefined;

    let animationFrame = null;

    const fitTitle = () => {
      animationFrame = null;

      const accentDot = row.querySelector(".strategy-accent-dot");
      const rowStyle = window.getComputedStyle(row);
      const gap = Number.parseFloat(rowStyle.columnGap || rowStyle.gap || "0") || 0;
      const dotWidth = accentDot?.getBoundingClientRect().width || 0;
      const availableWidth = Math.max(120, row.clientWidth - dotWidth - gap);

      // Measure the complete title at the maximum permitted size.
      titleElement.style.fontSize = `${STRATEGY_TITLE_MAX_FONT_PX}px`;
      titleElement.style.whiteSpace = "nowrap";
      titleElement.style.textWrap = "nowrap";
      titleElement.style.width = `${availableWidth}px`;

      const requiredWidthAtMaximum = Math.max(
        titleElement.scrollWidth,
        availableWidth,
      );

      const calculatedSize = (
        STRATEGY_TITLE_MAX_FONT_PX
        * availableWidth
        / requiredWidthAtMaximum
      );

      const shouldWrap = calculatedSize < STRATEGY_TITLE_MIN_FONT_PX;
      const fittedSize = shouldWrap
        ? STRATEGY_TITLE_MIN_FONT_PX
        : Math.min(
          STRATEGY_TITLE_MAX_FONT_PX,
          Math.floor(calculatedSize * 10) / 10,
        );

      titleElement.style.fontSize = `${fittedSize}px`;
      titleElement.style.whiteSpace = shouldWrap ? "normal" : "nowrap";
      titleElement.style.textWrap = shouldWrap ? "balance" : "nowrap";
      titleElement.style.width = "auto";
      titleElement.dataset.wrapped = shouldWrap ? "true" : "false";
    };

    const scheduleFit = () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(fitTitle);
    };

    const resizeObserver = new ResizeObserver(scheduleFit);
    resizeObserver.observe(row);
    scheduleFit();

    if (document.fonts?.ready) {
      document.fonts.ready.then(scheduleFit).catch(() => {});
    }

    return () => {
      resizeObserver.disconnect();
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
    };
  }, [title]);

  return (
    <div ref={rowRef} className="strategy-title-row">
      <i className="strategy-accent-dot" aria-hidden="true" />
      <h3 ref={titleRef} className="strategy-card-title">{title}</h3>
    </div>
  );
}

function StrategyHelp({ strategyCode, t }) {
  const details = STRATEGY_VISUALS[strategyCode] || {
    summary: "Uses its rules to choose between BUY, HOLD and SELL.",
    example: "If the setup is incomplete, it stays on HOLD.",
  };

  return (
    <span className="strategy-help" onPointerDown={(event) => event.stopPropagation()}>
      <button
        type="button"
        className="strategy-help-button"
        aria-label={t("How this strategy works")}
        title={t("How this strategy works")}
      >
        ?
      </button>
      <span className="strategy-help-popover" role="tooltip">
        {details.attribution && (
          <>
            <strong>{t("Creator or origin")}</strong>
            <span className="strategy-help-attribution">{t(details.attribution)}</span>
          </>
        )}
        <strong>{t("How it works")}</strong>
        <span>{t(details.summary)}</span>
        <strong>{t("Simple example")}</strong>
        <span>{t(details.example)}</span>
      </span>
    </span>
  );
}


function adaptivePatternConfirmation(strategy, decision, t) {
  const reason = String(decision?.reason || strategy?.last_decision_reason || "").toUpperCase();
  if (reason.includes("PATTERN_CONFIRMATION=APPROVED")) return { label: t("APPROVED"), tone: "positive" };
  if (reason.includes("PATTERN_CONFIRMATION=BLOCKED")) return { label: t("BLOCKED"), tone: "negative" };
  if (reason.includes("PATTERN_CONFIRMATION=NOT_REQUIRED_FOR_EXIT")) return { label: t("NOT REQUIRED"), tone: "neutral" };
  return { label: t("WAITING"), tone: "neutral" };
}

function adaptiveOpportunityStatus(strategy, decision, t) {
  const signal = decisionSignal(decision);
  const setupStatus = String(strategy?.setup_status || decision?.setup_status || "").toUpperCase();
  if (signal === "BUY" || setupStatus === "TRIGGERED") return { label: t("ENTRY CONFIRMED"), tone: "positive" };
  if (signal === "SELL") return { label: t("EXIT SIGNAL"), tone: "negative" };
  if (["ARMED", "ENTRY_ARMED"].includes(setupStatus)) return { label: t("WAITING FOR CONFIRMATION"), tone: "warning" };
  if (["ENTRY_WATCH", "WATCHING_ENTRY"].includes(setupStatus)) return { label: t("POSSIBLE ENTRY"), tone: "warning" };
  return { label: t("Waiting for next signal"), tone: "neutral" };
}

function AdaptiveSelectorOverview({ strategy, decision, language, t }) {
  const selectedName = strategy?.selector_active_strategy_name
    || decision?.selector_active_strategy_name
    || strategy?.selector_selected_strategy
    || decision?.selector_selected_strategy
    || t("No strategy selected");
  const regime = strategy?.selector_market_regime
    || decision?.selector_market_regime
    || t("Not calculated");
  const confirmation = adaptivePatternConfirmation(strategy, decision, t);
  const opportunity = adaptiveOpportunityStatus(strategy, decision, t);
  const confidence = decision?.ai_confidence
    ?? strategy?.ai_confidence
    ?? decision?.selector_confidence
    ?? strategy?.selector_confidence
    ?? null;

  return (
    <div className="adaptive-selector-overview" aria-label={t("Adaptive strategy summary")}>
      <div className="adaptive-selector-overview-item is-selected-strategy">
        <small>{t("Selected strategy")}</small>
        <strong>{t(selectedName)}</strong>
        <span>{t("Best validated strategy for this asset")}</span>
      </div>
      <div className="adaptive-selector-overview-item">
        <small>{t("Current regime")}</small>
        <strong>{t(regime)}</strong>
        <span>{t("Detected from recent market history")}</span>
      </div>
      <div className={`adaptive-selector-overview-item tone-${confirmation.tone}`}>
        <small>{t("Pattern confirmation")}</small>
        <strong>{confirmation.label}</strong>
        <span>{t("Local pattern model")}</span>
      </div>
      <div className="adaptive-selector-overview-item">
        <small>{t("Confidence")}</small>
        <strong>{confidence == null ? "—" : formatPercent(confidence, 1, language)}</strong>
        <span>{t("Historical similarity confidence")}</span>
      </div>
      <div className={`adaptive-selector-overview-item tone-${opportunity.tone}`}>
        <small>{t("Opportunity status")}</small>
        <strong>{opportunity.label}</strong>
        <span>{t("The engine waits for a valid signal")}</span>
      </div>
    </div>
  );
}

function DragHandle({ strategyCode, dragging, onPointerDown, onMove, t }) {
  return (
    <button
      type="button"
      className="strategy-drag-handle"
      aria-label={t("Drag to reorder strategy cards")}
      aria-pressed={dragging}
      title={t("Drag to reorder strategy cards")}
      onPointerDown={(event) => onPointerDown(event, strategyCode)}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onMove(strategyCode, -1);
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          onMove(strategyCode, 1);
        }
      }}
    >
      <svg viewBox="0 0 18 18" aria-hidden="true">
        {[4, 9, 14].flatMap((y) => [6, 12].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.15" />))}
      </svg>
    </button>
  );
}

export const StrategyCard = memo(function StrategyCard({
  strategy,
  decision,
  experiment,
  language,
  t,
  dragging,
  onPointerDown,
  onMove,
  onRetryHistory,
  retryingHistory,
  onRetryResearch,
  retryingResearch,
}) {
  const grossPnl = Number(strategy.gross_pnl || 0);
  const netPnl = Number(
    strategy.net_pnl
      ?? (Number(strategy.current_equity || strategy.initial_capital) - Number(strategy.initial_capital)),
  );
  const equity = Number(strategy.current_equity ?? strategy.initial_capital);
  const signal = decisionSignal(decision);
  const automationState = strategyAutomationState(strategy, decision, t);
  const positionLabel = strategy.has_open_position ? t("LONG") : t("NO POSITION");
  const entryPrice = Number(
    strategy.entry_execution_price
      || strategy.average_entry_price
      || strategy.entry_market_price
      || 0,
  );
  const openPnl = strategy.has_open_position && entryPrice > 0
    ? Number(strategy.asset_quantity || 0) * (Number(experiment.last_price || 0) - entryPrice)
    : 0;
  const entryCandleTimestamp = strategy.entry_candle_timestamp || strategy.entry_time || null;

  const visual = STRATEGY_VISUALS[strategy.strategy_code] || { accent: "#7182ff" };
  const adaptiveSelection = selectedStrategyLabel(strategy, decision, t);

  return (
    <article
      className={`strategy-card${strategy.strategy_code === "ADAPTIVE_STRATEGY_SELECTOR" ? " is-adaptive-selector" : ""} card-${pnlTone(netPnl)}${dragging ? " is-dragging" : ""}`}
      style={{ "--strategy-accent": visual.accent }}
      data-strategy-code={strategy.strategy_code}
      data-strategy-key={strategy.strategy_code}
    >
      <header className="strategy-card-header">
        <div className="strategy-header-top">
          <div className="strategy-label-row">
            <span>{t("Strategy")}</span>
            <StrategyHelp strategyCode={strategy.strategy_code} t={t} />
          </div>

          <div className="strategy-state-top">
            <span
              className={`signal-badge automation-${automationState.tone}`}
              title={`${automationState.title} ${t("Technical decision")}: ${t(signal)}.`}
              aria-label={`${automationState.label}. ${automationState.title}`}
            >
              <i className="signal-badge-dot" aria-hidden="true" />
              {automationState.label}
            </span>
            {strategy.strategy_code !== PINNED_STRATEGY_CODE && (
              <DragHandle
                strategyCode={strategy.strategy_code}
                dragging={dragging}
                onPointerDown={onPointerDown}
                onMove={onMove}
                t={t}
              />
            )}
          </div>
        </div>

        <ResponsiveStrategyTitle title={strategyName(strategy, t)} />

        {adaptiveSelection && strategy.strategy_code !== "ADAPTIVE_STRATEGY_SELECTOR" && (
          <span className="selected-strategy-chip" title={`${t("Active generated strategy")}: ${adaptiveSelection}`}>
            <small>{t("Active generated strategy")}</small>
            <strong>{adaptiveSelection}</strong>
          </span>
        )}
      </header>

      {visual.cardDescription && strategy.strategy_code !== "ADAPTIVE_STRATEGY_SELECTOR" && (
        <div className="strategy-hint-preview" title={t(visual.cardDescription)}>
          <span className="strategy-hint-icon" aria-hidden="true">i</span>
          <div>
            <small>{t("Hint")}</small>
            <p>{t(visual.cardDescription)}</p>
          </div>
        </div>
      )}

      {strategy.strategy_code === "ADAPTIVE_STRATEGY_SELECTOR" ? (
        <AdaptiveSelectorOverview
          strategy={strategy}
          decision={decision}
          language={language}
          t={t}
        />
      ) : (
      <div className="strategy-metrics">
        <div className="strategy-metric metric-wide">
          <span>{t("Market price")}</span>
          <strong>{formatPrice(experiment.last_price, language)} USDT</strong>
          <small>{t("Bid")} {formatPrice(experiment.best_bid, language)} · {t("Ask")} {formatPrice(experiment.best_ask, language)}</small>
        </div>

        <div className="strategy-metric">
          <span>{t("Net equity")}</span>
          <strong>{formatNumber(equity, 2, language)} USDT</strong>
          <small>{t("Initial")} {formatNumber(strategy.initial_capital, 2, language)}</small>
        </div>

        <div className={`strategy-metric metric-${pnlTone(grossPnl)}`}>
          <span>{t("Gross result")}</span>
          <strong>{formatSignedMoney(grossPnl, language)}</strong>
          <small>{formatPercent(strategy.gross_return, 3, language)}</small>
        </div>

        <div className={`strategy-metric metric-${pnlTone(netPnl)}`}>
          <span>{t("Net result")}</span>
          <strong>{formatSignedMoney(netPnl, language)}</strong>
          <small>{formatPercent(strategy.net_return, 3, language)}</small>
        </div>

        <div className={`strategy-metric metric-position ${strategy.has_open_position ? "is-open" : ""}`}>
          <span>{t("Position")}</span>
          <strong>{positionLabel}</strong>
          <small>{strategy.has_open_position ? `${t("Open P&L")} ${formatSignedMoney(openPnl, language)}` : t("Waiting for entry")}</small>
          {strategy.has_open_position && (
            <small className="entry-candle-time">
              {t("Entry candle (UTC)")}: {formatDateTime(entryCandleTimestamp, language)}
            </small>
          )}
        </div>
      </div>
      )}

      <AdaptiveResearchPanel
        strategy={strategy}
        decision={decision}
        experiment={experiment}
        language={language}
        t={t}
        onRetryHistory={onRetryHistory}
        retryingHistory={retryingHistory}
        onRetryResearch={onRetryResearch}
        retryingResearch={retryingResearch}
      />
    </article>
  );
});


