const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const localDevelopmentUrl = import.meta.env.DEV
  ? "http://127.0.0.1:8000"
  : "";

if (!configuredApiUrl && !localDevelopmentUrl) {
  throw new Error(
    "VITE_API_URL is not configured. Add it to the Railway frontend service variables and redeploy the service.",
  );
}

export const API_URL = (
  configuredApiUrl || localDevelopmentUrl
).replace(/\/+$/, "");

const JSON_HEADERS = Object.freeze({
  Accept: "application/json",
  "Content-Type": "application/json",
});

function buildApiUrl(path = "") {
  const normalizedPath = path.startsWith("/")
    ? path
    : `/${path}`;

  return `${API_URL}${normalizedPath}`;
}

function formatApiErrorDetail(detail, fallback) {
  if (!detail) {
    return fallback;
  }

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }

        if (item && typeof item === "object") {
          const location = Array.isArray(item.loc)
            ? item.loc.join(".")
            : "";

          const message =
            item.msg
            || item.message
            || item.detail
            || JSON.stringify(item);

          return location
            ? `${location}: ${message}`
            : message;
        }

        return String(item);
      })
      .filter(Boolean);

    return messages.length
      ? messages.join(" | ")
      : fallback;
  }

  if (typeof detail === "object") {
    return (
      detail.message
      || detail.msg
      || detail.error
      || detail.detail
      || JSON.stringify(detail)
    );
  }

  return String(detail);
}

export async function requestJson(path, options = {}) {
  let response;

  try {
    response = await fetch(buildApiUrl(path), {
      ...options,
      headers: {
        ...JSON_HEADERS,
        ...(options.headers || {}),
      },
    });
  } catch (cause) {
    const error = new Error(
      "Unable to connect to the API. Check the backend URL and network connection.",
    );

    error.cause = cause;
    throw error;
  }

  if (!response.ok) {
    const fallback = `HTTP ${response.status}`;
    let message = fallback;

    try {
      const payload = await response.json();

      message = formatApiErrorDetail(
        payload?.detail
          ?? payload?.message
          ?? payload?.error,
        fallback,
      );
    } catch {
      try {
        const body = await response.text();

        if (body.trim()) {
          message = body.trim();
        }
      } catch {
        // Preserve the HTTP fallback.
      }
    }

    const error = Object.assign(new Error(message), {
      status: response.status,
      path,
    });

    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";

  if (!contentType.includes("application/json")) {
    return null;
  }

  return response.json();
}
