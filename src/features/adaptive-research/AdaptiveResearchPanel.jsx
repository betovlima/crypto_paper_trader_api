import { useLiveNow } from "../../hooks/useLiveNow";
import { decisionSignal, formatDuration, formatNumber, formatPercent, formatPrice, parseApiDate, parseJsonObject } from "../../shared/dashboardUtils";

export function Countdown({ target, expiredLabel = null }) {
  const now = useLiveNow(Boolean(target));
  const targetDate = parseApiDate(target);
  const remaining = targetDate ? targetDate.getTime() - now : null;

  return (
    <span className="live-countdown" aria-live="off" aria-atomic="true">
      {targetDate
        ? (remaining <= 0 && expiredLabel ? expiredLabel : formatDuration(remaining))
        : "—"}
    </span>
  );
}

function AdaptiveResearchCountdownRing({ target, t }) {
  const now = useLiveNow(Boolean(target));
  const targetDate = parseApiDate(target);
  const remaining = targetDate ? targetDate.getTime() - now : null;
  const researchCycleMs = 12 * 60 * 60 * 1000;
  const progress = remaining == null
    ? 0
    : Math.max(0, Math.min(1, remaining / researchCycleMs));
  const degrees = Math.round(progress * 360);
  const displayValue = targetDate
    ? (remaining <= 0 ? t("Updating…") : formatDuration(remaining))
    : "—";

  return (
    <div
      className="decision-countdown-ring"
      style={{ "--decision-progress": `${degrees}deg` }}
      aria-label={`${t("Next adaptive research")}: ${displayValue}`}
    >
      <div className="decision-countdown-ring-inner">
        <small>{t("Next adaptive research")}</small>
        <strong>{displayValue}</strong>
        <span>{targetDate ? t("Automatic research cycle") : t("Waiting for schedule")}</span>
      </div>
    </div>
  );
}


export function AdaptiveResearchPanel({
  strategy,
  decision,
  experiment,
  language,
  t,
  onRetryHistory,
  retryingHistory,
  onRetryResearch,
  retryingResearch,
}) {
  if (strategy?.strategy_code !== "ADAPTIVE_STRATEGY_SELECTOR") return null;

  const value = (key) => strategy?.[key] ?? decision?.[key] ?? null;
  const researchStatus = value("selector_research_status") || "WAITING_FOR_VALID_STRATEGY";
  const nextResearchAt = value("selector_next_research_at");
  const researchDetails = parseJsonObject(value("selector_candidate_scores"));
  const history = parseJsonObject(researchDetails.history);
  const historySync = parseJsonObject(researchDetails.history_sync);
  const patternAnalysis = parseJsonObject(researchDetails.pattern_analysis);
  const bestCandidate = researchDetails.best_candidate || null;
  const currentPatterns = Array.isArray(patternAnalysis.current_patterns)
    ? patternAnalysis.current_patterns
    : [];
  const dominantPatterns = Array.isArray(patternAnalysis.dominant_historical_patterns)
    ? patternAnalysis.dominant_historical_patterns
    : [];

  const signal = decisionSignal(decision);
  const setupStatus = String(strategy?.setup_status || decision?.setup_status || "").toUpperCase();
  const isEntryConfirmed = signal === "BUY" || setupStatus === "TRIGGERED";
  const isEntryArmed = setupStatus === "ARMED" || setupStatus === "ENTRY_ARMED";
  const isEntryWatch = setupStatus === "ENTRY_WATCH" || setupStatus === "WATCHING_ENTRY";
  const showEntryOpportunity = !strategy?.has_open_position
    && (isEntryConfirmed || isEntryArmed || isEntryWatch);

  const opportunityLabel = isEntryConfirmed
    ? t("ENTRY CONFIRMED")
    : isEntryArmed
      ? t("WAITING FOR CONFIRMATION")
      : t("POSSIBLE ENTRY");
  const opportunityTone = isEntryConfirmed ? "confirmed" : isEntryArmed ? "armed" : "watch";
  const candidateName = value("selector_active_strategy_name")
    || bestCandidate?.name
    || t("Adaptive pattern strategy");
  const triggerPrice = strategy?.entry_trigger_price
    ?? decision?.execution_reference_price
    ?? null;
  const stopPrice = decision?.stop_loss_override
    ?? strategy?.initial_setup_stop_price
    ?? strategy?.stop_loss_price
    ?? null;
  const targetPrice = decision?.take_profit_override
    ?? decision?.potential_target_price
    ?? strategy?.setup_target_price
    ?? strategy?.take_profit_price
    ?? null;

  const cleanCandleCount = history.clean_candles ?? null;
  const requiredCandleCount = history.required_clean_candles ?? null;
  const targetCandleCount = history.target_history_candles ?? historySync.target_candles ?? null;
  const storedCandleCount = history.stored_candles
    ?? historySync.stored_candles
    ?? patternAnalysis.history_candles_analyzed
    ?? null;
  const executionTimeframe = researchDetails.execution_timeframe
    || patternAnalysis.execution_timeframe
    || experiment?.execution_timeframe
    || "—";
  const similarPatterns = patternAnalysis.similar_pattern_count ?? 0;
  const positiveRate = patternAnalysis.positive_after_cost_rate;
  const expectedReturn = patternAnalysis.expected_next_return;
  const patternConfidence = patternAnalysis.similarity_confidence;
  const rangeState = patternAnalysis.range_state || "UNKNOWN";
  const rangeScore = patternAnalysis.range_bound_score;
  const rangePosition = patternAnalysis.range_position;
  const rangeSupport = patternAnalysis.range_support;
  const rangeResistance = patternAnalysis.range_resistance;
  const rangePositionLabel = rangePosition == null
    ? t("Not calculated")
    : rangePosition <= 0.33
      ? t("Lower range")
      : rangePosition >= 0.67
        ? t("Upper range")
        : t("Middle range");

  const aiStatus = researchDetails.ai_hypothesis_status
    || researchDetails.web_research_status
    || value("selector_ai_review_status")
    || "NOT_USED";
  const aiError = String(
    researchDetails.ai_hypothesis_error
      || researchDetails.web_research_error
      || researchDetails.ai_review_error
      || value("selector_last_error")
      || "",
  ).trim();
  const hasAiError = Boolean(aiError) && aiStatus === "ERROR";
  const isWaitingForHistory = researchStatus === "WAITING_FOR_HISTORY";
  const canRetryResearch = !strategy?.has_open_position && !isWaitingForHistory;

  return (
    <section className="adaptive-research-strip" aria-label={t("Adaptive pattern research details")}>
      {showEntryOpportunity && (
        <div className={`adaptive-entry-opportunity opportunity-${opportunityTone}`}>
          <div className="adaptive-entry-opportunity-heading">
            <div>
              <small>{t("Opportunity")}</small>
              <strong>{t(candidateName)}</strong>
            </div>
            <span>{opportunityLabel}</span>
          </div>
          <div className="adaptive-entry-opportunity-values">
            {triggerPrice != null && (
              <div><small>{t("Entry price")}</small><strong>{formatPrice(triggerPrice, language)}</strong></div>
            )}
            {stopPrice != null && (
              <div><small>{t("Protection")}</small><strong>{formatPrice(stopPrice, language)}</strong></div>
            )}
            {targetPrice != null && (
              <div><small>{t("Target")}</small><strong>{formatPrice(targetPrice, language)}</strong></div>
            )}
            <div><small>{t("Validity")}</small><strong>{t("Next candle")}</strong></div>
          </div>
        </div>
      )}

      <div className="adaptive-strip-facts">
        <div className="adaptive-strip-fact is-decision-countdown">
          <AdaptiveResearchCountdownRing target={nextResearchAt} t={t} />
        </div>
        <div className="adaptive-strip-fact">
          <small>{t("History")}</small>
          <strong>{storedCandleCount == null ? "—" : `${storedCandleCount}${targetCandleCount == null ? "" : `/${targetCandleCount}`}`}</strong>
          <span>{t("candles")}</span>
        </div>
        <div className="adaptive-strip-fact">
          <small>{t("Current patterns")}</small>
          <strong>{currentPatterns.length ? currentPatterns.slice(0, 2).map(t).join(" · ") : t("No confirmed pattern")}</strong>
          <span>{dominantPatterns.length ? `${t("Historical")}: ${dominantPatterns.slice(0, 2).map(t).join(" · ")}` : t("Waiting for confirmation")}</span>
        </div>
        <div className="adaptive-strip-fact">
          <small>{t("Similar cases")}</small>
          <strong>{similarPatterns || "—"}</strong>
          <span>{positiveRate == null ? t("Not calculated") : `${t("After costs")}: ${formatPercent(positiveRate, 1, language)}`}</span>
        </div>
        <div className="adaptive-strip-fact">
          <small>{t("Next candle")}</small>
          <strong>{expectedReturn == null ? "—" : formatPercent(expectedReturn, 2, language)}</strong>
          <span>{patternConfidence == null ? t("Not calculated") : `${t("Confidence")}: ${formatPercent(patternConfidence, 1, language)}`}</span>
        </div>
        <div className="adaptive-strip-fact is-range-evaluation">
          <small>{t("Sideways market")}</small>
          <strong>{t(rangeState)}</strong>
          <span>{rangeScore == null ? t("Not calculated") : `${t("Range score")}: ${formatNumber(rangeScore, 1, language)}/100`}</span>
        </div>
        <div className="adaptive-strip-fact is-range-position">
          <small>{t("Price range")}</small>
          <strong>{rangePositionLabel}</strong>
          <span>{rangeSupport == null || rangeResistance == null ? t("Calculating range") : `${formatPrice(rangeSupport, language)} – ${formatPrice(rangeResistance, language)}`}</span>
        </div>
      </div>

      <details className="adaptive-technical-details">
        <summary>{t("Technical details")}</summary>
        <div className="adaptive-technical-details-content">
          <div><small>{t("Research status")}</small><strong>{t(researchStatus)}</strong></div>
          <div><small>{t("Hypotheses")}</small><strong>{researchDetails.tested_count ?? "—"}</strong></div>
          <div><small>{t("Approved")}</small><strong>{researchDetails.approved_count ?? "—"}</strong></div>
          <div><small>{t("Usable candles")}</small><strong>{cleanCandleCount == null || requiredCandleCount == null ? "—" : `${cleanCandleCount}/${requiredCandleCount}`}</strong></div>
        </div>

        {isWaitingForHistory && (
          <button
            type="button"
            className="secondary-button adaptive-history-retry-button"
            onClick={() => onRetryHistory?.(strategy)}
            disabled={retryingHistory}
          >
            {retryingHistory ? t("Retrying history…") : t("Retry history now")}
          </button>
        )}

        {hasAiError && <code className="adaptive-technical-error" title={aiError}>{aiError}</code>}

        {canRetryResearch && (
          <button
            type="button"
            className="secondary-button adaptive-research-retry-button"
            onClick={() => onRetryResearch?.(strategy)}
            disabled={retryingResearch}
          >
            {retryingResearch ? t("Analyzing…") : t("Analyze again")}
          </button>
        )}
      </details>
    </section>
  );
}


