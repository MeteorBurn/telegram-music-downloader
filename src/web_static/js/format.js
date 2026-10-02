// Formatting for numbers, sizes and times. Missing values render as "--".

const integer = new Intl.NumberFormat("en-US");
const dateTime = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateOnly = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

export const MISSING = "--";

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
const pad = (value) => String(value).padStart(2, "0");

export function fmtInt(value) {
  return isNumber(value) ? integer.format(value) : MISSING;
}

/**
 * Megabytes to a { value, unit } pair: GB above 1024 MB, KB below 0.1 MB. A zero reported
 * for a non-empty set (the API rounds to 0.1 MB) is shown as "<0.1 MB" when `nonEmpty` is set.
 */
export function fmtSize(megabytes, { nonEmpty = false } = {}) {
  if (!isNumber(megabytes)) return { value: MISSING, unit: "MB" };
  if (megabytes >= 1024) {
    const gigabytes = megabytes / 1024;
    return { value: gigabytes.toFixed(gigabytes >= 100 ? 1 : 2), unit: "GB" };
  }
  if (megabytes > 0 && megabytes < 0.1) {
    const kilobytes = megabytes * 1024;
    return { value: kilobytes.toFixed(kilobytes >= 10 ? 0 : 1), unit: "KB" };
  }
  if (megabytes === 0 && nonEmpty) return { value: "<0.1", unit: "MB" };
  return { value: megabytes.toFixed(megabytes >= 100 ? 0 : 1), unit: "MB" };
}

export function fmtSizeText(megabytes, options) {
  const { value, unit } = fmtSize(megabytes, options);
  return value === MISSING ? MISSING : `${value} ${unit}`;
}

export function fmtDecimal(value, digits = 1) {
  return isNumber(value) ? value.toFixed(digits) : MISSING;
}

/** Seconds to mm:ss, or h:mm:ss past an hour. */
export function fmtDuration(seconds) {
  if (!isNumber(seconds) || seconds < 0) return "--:--";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`;
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function fmtDateTime(value) {
  const date = parseDate(value);
  return date ? dateTime.format(date) : MISSING;
}

export function fmtDate(value) {
  const date = parseDate(value);
  return date ? dateOnly.format(date) : MISSING;
}

/** "2026-01-01" to "Jan 1, 2026" without a time zone shift. */
export function fmtDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  if (!match) return value ? String(value) : MISSING;
  return dateOnly.format(new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

export function fmtRelative(value) {
  const date = parseDate(value);
  if (!date) return MISSING;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 86400 * 7) return `${Math.round(seconds / 86400)} d ago`;
  return dateOnly.format(date);
}

/** "2026-10-03T00:15:30" to "00:15:30". */
export function fmtClock(timestamp) {
  const text = String(timestamp ?? "");
  return text.length >= 19 ? text.slice(11, 19) : text;
}

/** "worker_3" to "W3". */
export function workerTag(workerId) {
  const match = /(\d+)\s*$/.exec(String(workerId ?? ""));
  return match ? `W${match[1]}` : String(workerId ?? "W");
}

export function workerIndex(workerId) {
  const match = /(\d+)\s*$/.exec(String(workerId ?? ""));
  return match ? Number(match[1]) : null;
}

export function plural(count, one, many = `${one}s`) {
  return count === 1 ? one : many;
}

export function initials(user) {
  const first = String(user?.first_name ?? "").trim();
  const last = String(user?.last_name ?? "").trim();
  const username = String(user?.username ?? "").trim();
  const letters = `${first.slice(0, 1)}${last.slice(0, 1)}` || username.slice(0, 2) || "TG";
  return letters.toUpperCase();
}

export function fullName(user) {
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
  return name || (user?.username ? `@${user.username}` : "Telegram account");
}
