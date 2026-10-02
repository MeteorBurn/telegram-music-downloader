// Log store: one backlog request, then a live EventSource. Entries are deduplicated by id
// and capped at 2000 lines. It keeps running after the Logs view is left.

import { api } from "./api.js";

export const LOG_CAP = 2000;
const BACKLOG = 500;
const RETRY_MIN = 1000;
const RETRY_MAX = 15000;

const state = {
  entries: [],
  status: "idle", // idle | loading | live | reconnecting | offline
  lastId: 0,
};
const listeners = new Set();
let source = null;
let retryTimer = null;
let retryDelay = RETRY_MIN;
let started = false;
let backfilling = false;
let buffered = [];

function emit(event) {
  for (const listener of [...listeners]) listener(event);
}

function setStatus(status) {
  if (state.status === status) return;
  state.status = status;
  emit({ type: "status" });
}

function ingest(list) {
  const fresh = [];
  for (const entry of list) {
    if (!entry || typeof entry.id !== "number" || entry.id <= state.lastId) continue;
    state.lastId = entry.id;
    fresh.push(entry);
  }
  if (!fresh.length) return;
  state.entries.push(...fresh);
  const overflow = state.entries.length - LOG_CAP;
  if (overflow > 0) state.entries.splice(0, overflow);
  emit({ type: "append", entries: fresh });
}

async function backfill() {
  backfilling = true;
  try {
    const data = await api.logs({ limit: BACKLOG, afterId: 0 });
    const list = Array.isArray(data?.entries) ? data.entries : [];
    const newest = list.length ? list[list.length - 1].id : 0;
    if (list.length && newest < state.lastId) {
      // Ids started over, so the server was restarted. Keep the old lines above a divider.
      state.lastId = 0;
      state.entries.push({ divider: true, message: "Server restarted" });
      emit({ type: "reset" });
    }
    ingest(list);
  } finally {
    backfilling = false;
    const pending = buffered;
    buffered = [];
    ingest(pending);
  }
}

function connect() {
  clearTimeout(retryTimer);
  source = new EventSource("/api/logs/stream");
  source.addEventListener("open", () => {
    retryDelay = RETRY_MIN;
    // Every (re)connect is followed by a backlog request, which closes any gap.
    backfill()
      .then(() => setStatus("live"))
      .catch(() => setStatus("live"));
  });
  source.addEventListener("log", (event) => {
    let entry;
    try {
      entry = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    if (backfilling) buffered.push(entry);
    else ingest([entry]);
  });
  source.addEventListener("error", () => {
    if (source.readyState === EventSource.CLOSED) {
      // The browser gave up (for example a non-200 answer): retry by hand with backoff.
      source.close();
      setStatus("offline");
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, RETRY_MAX);
    } else {
      setStatus("reconnecting");
    }
  });
}

export function startLogs() {
  if (started) return;
  started = true;
  setStatus("loading");
  connect();
}

export function subscribeLogs(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const logState = state;
