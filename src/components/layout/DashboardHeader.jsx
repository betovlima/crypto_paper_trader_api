import { LANGUAGE_OPTIONS } from "../../i18n";
import { Countdown } from "../../features/adaptive-research/AdaptiveResearchPanel";
import { statusLabel } from "../../shared/dashboardUtils";

function FlagIcon({ code }) {
  if (code === "pt") {
    return (
      <svg className="flag-icon" viewBox="0 0 30 20" role="img" aria-label="Brazil">
        <rect width="30" height="20" rx="1.5" fill="#009B3A" />
        <path d="M15 2.8 27 10 15 17.2 3 10Z" fill="#FFDF00" />
        <circle cx="15" cy="10" r="4.55" fill="#002776" />
        <path d="M10.9 9.15c2.75-.55 5.35-.24 8.2.98" fill="none" stroke="#fff" strokeWidth=".75" />
      </svg>
    );
  }

  if (code === "en") {
    return (
      <svg className="flag-icon" viewBox="0 0 30 20" role="img" aria-label="United States">
        <rect width="30" height="20" rx="1.5" fill="#fff" />
        {[0, 4, 8, 12, 16].map((y) => (
          <rect key={y} y={y} width="30" height="2" fill="#B22234" />
        ))}
        <rect width="13" height="10.8" rx=".5" fill="#3C3B6E" />
        {[2.2, 5.1, 8, 10.9].map((x) =>
          [2.1, 5.1, 8.1].map((y) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r=".55" fill="#fff" />
          )),
        )}
      </svg>
    );
  }

  return (
    <svg className="flag-icon" viewBox="0 0 30 20" role="img" aria-label="Spain">
      <rect width="30" height="20" rx="1.5" fill="#AA151B" />
      <rect y="5" width="30" height="10" fill="#F1BF00" />
      <rect x="8.2" y="7.3" width="2.5" height="5.4" rx=".35" fill="#AA151B" opacity=".9" />
    </svg>
  );
}

export function LanguageSelector({ language, onChange, t }) {
  return (
    <div className="language-selector" role="group" aria-label={t("Language")}>
      {LANGUAGE_OPTIONS.map((option) => (
        <button
          key={option.code}
          type="button"
          className={language === option.code ? "language-button active" : "language-button"}
          onClick={() => onChange(option.code)}
          aria-label={option.label}
          aria-pressed={language === option.code}
          title={option.label}
        >
          <FlagIcon code={option.code} />
        </button>
      ))}
    </div>
  );
}

export function RunningExperimentTopbarSummary({ summary, t }) {
  if (!summary?.visible) return null;

  return (
    <section className="running-topbar-context" aria-label={t("Running simulation summary")}>
      <div className="topbar-market-context">
        <small>{t("Selected market")}</small>
        <div className="topbar-market-value-row">
          <strong>{summary.market_label || "—"}</strong>
          <span className={`topbar-live-state is-${summary.status_tone || "running"}`}>
            <i aria-hidden="true" />
            {statusLabel(summary.status, t)}
          </span>
        </div>
      </div>

      <div className="topbar-candle-context">
        <span>
          <small>{t("Decision candle")}</small>
          <strong>{summary.decision_timeframe_label || "—"}</strong>
        </span>
        <i aria-hidden="true" />
        <span>
          <small>{t("Trend context")}</small>
          <strong>{summary.trend_timeframe_label || "—"}</strong>
        </span>
      </div>
    </section>
  );
}

export function ExperimentCycleBar({ summary, t }) {
  if (!summary?.visible) return null;

  return (
    <section className="experiment-cycle-bar" aria-label={t("Experiment cycle")}>
      <div className="experiment-cycle-intro">
        <span className="experiment-cycle-icon" aria-hidden="true">↻</span>
        <strong>{t("Cycle")}</strong>
      </div>

      <div className="experiment-cycle-next">
        <small>{t("Next analysis")}</small>
        <strong>
          <Countdown
            target={summary.next_analysis_at}
            expiredLabel={t("Processing closed candle")}
          />
        </strong>
        <span>{t("Decision candle")}: {summary.decision_timeframe_label || "—"}</span>
      </div>

      <div className="experiment-cycle-update">
        <small>{t("Last price update")}</small>
        <strong>{summary.last_market_update_label || "—"}</strong>
        <span>{summary.market_label || "—"}</span>
      </div>
    </section>
  );
}


