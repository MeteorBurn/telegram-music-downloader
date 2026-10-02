// HTTP client for the local API (CONTRACT.md). Every failure becomes an ApiError.

export class ApiError extends Error {
  constructor({ status, code, message, details }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = Array.isArray(details) ? details : [];
  }
}

const STATUS_CODES = { 400: "invalid", 404: "not_found", 409: "busy", 412: "not_authorized", 415: "unsupported_media_type" };

function fallbackMessage(status) {
  if (status >= 500) return "The local server reported an internal error. See the Logs view for details.";
  return `The request was rejected (HTTP ${status}).`;
}

function toApiError(status, data) {
  const error = data && typeof data === "object" ? data.error : null;
  if (error && typeof error === "object") {
    return new ApiError({
      status,
      code: String(error.code ?? STATUS_CODES[status] ?? "error"),
      message: String(error.message ?? fallbackMessage(status)),
      details: Array.isArray(error.details) ? error.details.map(String) : [],
    });
  }
  // Framework default shape: {"detail": "text"} or {"detail": [{"loc": [...], "msg": "..."}]}.
  const detail = data && typeof data === "object" ? data.detail : null;
  if (typeof detail === "string") {
    return new ApiError({ status, code: STATUS_CODES[status] ?? "error", message: detail });
  }
  if (Array.isArray(detail)) {
    const details = detail.map((item) => {
      if (!item || typeof item !== "object") return String(item);
      const location = (item.loc ?? []).filter((part) => part !== "body").join(".");
      return `${location} ${item.msg ?? ""}`.trim();
    });
    return new ApiError({ status, code: "invalid", message: "The request was rejected.", details });
  }
  return new ApiError({ status, code: STATUS_CODES[status] ?? "error", message: fallbackMessage(status) });
}

async function request(method, path, body, { timeout = 20000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const init = { method, signal: controller.signal, cache: "no-store", headers: { Accept: "application/json" } };
  if (method !== "GET") {
    // The server answers 415 without this header, even for an empty body.
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body ?? {});
  }
  let status;
  let text;
  try {
    const response = await fetch(path, init);
    status = response.status;
    text = await response.text();
  } catch (error) {
    const timedOut = error?.name === "AbortError";
    throw new ApiError({
      status: 0,
      code: timedOut ? "timeout" : "network",
      message: timedOut
        ? "The local server did not answer in time."
        : "Cannot reach the local server. Check that it is still running.",
    });
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = null;
    }
  }
  if (status < 200 || status >= 300) throw toApiError(status, data);
  return data;
}

const get = (path, options) => request("GET", path, undefined, options);
const post = (path, body, options) => request("POST", path, body, options);

export const api = {
  health: () => get("/api/health"),
  session: () => get("/api/session", { timeout: 8000 }),
  startSession: (options) => post("/api/session/start", options, { timeout: 30000 }),
  stopSession: () => post("/api/session/stop", {}),
  stats: () => get("/api/stats", { timeout: 30000 }),
  cleanup: () => post("/api/cleanup", {}, { timeout: 60000 }),
  config: () => get("/api/config"),
  saveConfig: (patch) => request("PUT", "/api/config", patch, { timeout: 30000 }),
  auth: () => get("/api/auth", { timeout: 30000 }),
  authPhone: (phone) => post("/api/auth/phone", { phone }, { timeout: 60000 }),
  authCode: (code) => post("/api/auth/code", { code }, { timeout: 60000 }),
  authPassword: (password) => post("/api/auth/password", { password }, { timeout: 60000 }),
  authCancel: () => post("/api/auth/cancel", {}, { timeout: 30000 }),
  authLogout: () => post("/api/auth/logout", {}, { timeout: 30000 }),
  logs: ({ limit = 500, afterId = 0 } = {}) => get(`/api/logs?limit=${limit}&after_id=${afterId}`),
};
