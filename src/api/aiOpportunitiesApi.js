import { requestJson } from "./client";

export function getAIOpportunityScannerStatus() {
  return requestJson("/api/v1/ai-opportunities/status");
}

export function listLatestAIOpportunities(limit = 10) {
  return requestJson(`/api/v1/ai-opportunities/latest?limit=${encodeURIComponent(limit)}`);
}
