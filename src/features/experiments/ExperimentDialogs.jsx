import { translateDynamicText } from "../../i18n";
import { formatMarketPair, formatPercent } from "../../shared/dashboardUtils";

export function SetupDialog({
  configuration,
  form,
  setForm,
  hasRunningExperiment,
  saving,
  onSubmit,
  onSelectProfile,
  onStop,
  onClose,
  language,
  t,
}) {
  const selectedProfile = configuration?.trading_profiles?.find((item) => item.code === form.trading_profile);

  return (
    <div
      className="setup-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <section
        id="setup-configuration-dialog"
        className="setup-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-dialog-title"
      >
        <div className="setup-menu-header">
          <div>
            <span>{t("Setup")}</span>
            <h2 id="setup-dialog-title">{t("New experiment")}</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            disabled={saving}
            aria-label={t("Close configuration")}
          >
            ×
          </button>
        </div>

        <form onSubmit={onSubmit} className="setup-menu-form">
        <label className="setup-field setup-market-field">
          <span>{t("Market")}</span>
          <input
            value={form.market}
            onChange={(event) => setForm((previous) => ({ ...previous, market: event.target.value.toUpperCase() }))}
            onBlur={() => setForm((previous) => ({ ...previous, market: formatMarketPair(previous.market) }))}
            placeholder="BTC/USDT"
            required
          />
        </label>

        <label className="setup-field">
          <span>{t("Duration")}</span>
          <div className="input-with-suffix">
            <input
              type="number"
              min="0.02"
              max="168"
              step="0.01"
              value={form.duration_hours}
              onChange={(event) => setForm((previous) => ({ ...previous, duration_hours: event.target.value }))}
              required
            />
            <em>{t("hours")}</em>
          </div>
        </label>

        <label className="setup-field">
          <span>{t("Capital")}</span>
          <div className="input-with-suffix">
            <input
              type="number"
              min="1"
              step="0.01"
              value={form.initial_capital}
              onChange={(event) => setForm((previous) => ({ ...previous, initial_capital: event.target.value }))}
              required
            />
            <em>USDT</em>
          </div>
        </label>

        <fieldset className="setup-profile-field">
          <legend>{t("Trading profile")}</legend>
          <div className="profile-options">
            {(configuration?.trading_profiles || []).map((profile) => (
              <button
                key={profile.code}
                type="button"
                className={form.trading_profile === profile.code ? "profile-option active" : "profile-option"}
                onClick={() => onSelectProfile(profile.code)}
              >
                <strong>{translateDynamicText(language, profile.display_name)}</strong>
                <small>{profile.decision_timeframe} {t("decision")} · {profile.trend_timeframe} {t("trend")}</small>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="setup-actions">
          <button
            type="button"
            className="reset-button setup-reset-button"
            onClick={onStop}
            disabled={saving || !hasRunningExperiment}
          >
            {t("Stop experiment")}
          </button>
          <button className="primary-button" disabled={saving || hasRunningExperiment}>
            {saving ? t("Starting…") : t("Start simulation")}
          </button>
          {configuration && (
            <p className="fee-note">
              {t("MEXC taker fee")}: <strong>{formatPercent(configuration.taker_fee_rate, 2, language)} {t("per side")}</strong>
            </p>
          )}
        </div>

          {selectedProfile && (
            <div className="profile-summary setup-profile-summary">
              <span>{translateDynamicText(language, selectedProfile.description)}</span>
              <strong>{selectedProfile.fast_ema_period}/{selectedProfile.slow_ema_period}/{selectedProfile.regime_ema_period} {t("EMA structure")}</strong>
            </div>
          )}
        </form>
      </section>
    </div>
  );
}

export function StopDialog({
  open,
  adminKey,
  setAdminKey,
  closeOpenPositions,
  setCloseOpenPositions,
  error,
  stopping,
  onClose,
  onConfirm,
  t,
}) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !stopping) onClose();
    }}>
      <section className="reset-dialog stop-dialog" role="dialog" aria-modal="true" aria-labelledby="stop-title">
        <div className="reset-icon" aria-hidden="true">!</div>
        <span>{t("Confirmation")}</span>
        <h2 id="stop-title">{t("Stop running experiment?")}</h2>
        <p>{t("The experiment will stop and its data will be kept.")}</p>

        <form onSubmit={onConfirm}>
          <fieldset className="stop-position-options">
            <legend>{t("Open positions")}</legend>
            <label>
              <input
                type="radio"
                name="close-open-positions"
                checked={closeOpenPositions}
                onChange={() => setCloseOpenPositions(true)}
              />
              <span>{t("Close positions at the current price")}</span>
            </label>
            <label>
              <input
                type="radio"
                name="close-open-positions"
                checked={!closeOpenPositions}
                onChange={() => setCloseOpenPositions(false)}
              />
              <span>{t("Keep positions frozen")}</span>
            </label>
          </fieldset>

          <label htmlFor="admin-api-key">{t("Admin key")}</label>
          <input
            id="admin-api-key"
            type="password"
            autoComplete="off"
            value={adminKey}
            onChange={(event) => setAdminKey(event.target.value)}
            placeholder={t("Enter the admin key")}
            autoFocus
          />
          {error && <div className="modal-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={onClose} disabled={stopping}>{t("Cancel")}</button>
            <button type="submit" className="danger-button" disabled={stopping || !adminKey.trim()}>
              {stopping ? t("Stopping…") : t("Stop experiment")}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function HistoryRetryDialog({
  open,
  adminKey,
  setAdminKey,
  error,
  retrying,
  onClose,
  onConfirm,
  t,
}) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !retrying) onClose();
    }}>
      <section
        className="reset-dialog history-retry-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-retry-title"
      >
        <div className="reset-icon" aria-hidden="true">↻</div>
        <span>{t("Confirmation")}</span>
        <h2 id="history-retry-title">{t("Update history now?")}</h2>
        <p>{t("Older candles will be loaded and the analysis will run again.")}</p>

        <form onSubmit={onConfirm}>
          <label htmlFor="history-admin-api-key">{t("Admin key")}</label>
          <input
            id="history-admin-api-key"
            type="password"
            autoComplete="off"
            value={adminKey}
            onChange={(event) => setAdminKey(event.target.value)}
            placeholder={t("Enter the admin key")}
            autoFocus
          />
          {error && <div className="modal-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={onClose} disabled={retrying}>
              {t("Cancel")}
            </button>
            <button type="submit" className="primary-button" disabled={retrying || !adminKey.trim()}>
              {retrying ? t("Updating history…") : t("Update history")}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function ResearchRetryDialog({
  open,
  adminKey,
  setAdminKey,
  error,
  retrying,
  onClose,
  onConfirm,
  t,
}) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !retrying) onClose();
    }}>
      <section
        className="reset-dialog research-retry-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="research-retry-title"
      >
        <div className="reset-icon" aria-hidden="true">↻</div>
        <span>{t("Confirmation")}</span>
        <h2 id="research-retry-title">{t("Analyze the current pattern again?")}</h2>
        <p>{t("The history, pattern search and backtests will run again.")}</p>

        <form onSubmit={onConfirm}>
          <label htmlFor="research-admin-api-key">{t("Admin key")}</label>
          <input
            id="research-admin-api-key"
            type="password"
            autoComplete="off"
            value={adminKey}
            onChange={(event) => setAdminKey(event.target.value)}
            placeholder={t("Enter the admin key")}
            autoFocus
          />
          {error && <div className="modal-error" role="alert">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={onClose} disabled={retrying}>
              {t("Cancel")}
            </button>
            <button type="submit" className="primary-button" disabled={retrying || !adminKey.trim()}>
              {retrying ? t("Analyzing…") : t("Analyze again")}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}


