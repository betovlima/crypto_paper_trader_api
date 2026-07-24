import { requestJson } from "./client";

function strategyQuery(strategyCode) {
  return `strategy_code=${encodeURIComponent(strategyCode)}`;
}

function queryString(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, value);
  });
  return search.toString();
}

export function listStrategyAccounts(experimentId) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategies`);
}

export function getStrategyComparison(experimentId) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-comparison`);
}

export function getStrategyComparisonHistory(experimentId, limit = 4) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-comparison/history?limit=${encodeURIComponent(limit)}`);
}

export function listStrategyDecisions(experimentId, strategyCode, limit = 80) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-decisions?${strategyQuery(strategyCode)}&limit=${encodeURIComponent(limit)}`);
}

export function listStrategyTrades(experimentId, strategyCode) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-trades?${strategyQuery(strategyCode)}`);
}

export function listStrategyTradeHistory(experimentId, params = {}) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-trades/history?${queryString(params)}`);
}

export function listStrategyMarketSnapshots(experimentId, strategyCode, limit = 120) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(experimentId)}/strategy-market-snapshots?${strategyQuery(strategyCode)}&limit=${encodeURIComponent(limit)}`);
}
