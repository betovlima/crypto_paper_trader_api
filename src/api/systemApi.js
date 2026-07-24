import { requestJson } from "./client";

export function getPublicConfiguration() {
  return requestJson("/api/v1/config");
}
