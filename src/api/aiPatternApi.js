import { requestJson } from "./client";

export function getAIPatternStatus(experimentId) {
  return requestJson(
    `/api/v1/experiments/${encodeURIComponent(experimentId)}/ai-pattern-trader/status`,
  );
}

export function listAIPatternPredictions(experimentId, limit = 80) {
  return requestJson(
    `/api/v1/experiments/${encodeURIComponent(experimentId)}/ai-pattern-trader/predictions?limit=${encodeURIComponent(limit)}`,
  );
}
