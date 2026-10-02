// Shared state: session status (polled) and Telegram account status.

import { api } from "./api.js";

export function createStore(initial) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(next) {
      state = typeof next === "function" ? next(state) : next;
      for (const listener of [...listeners]) listener(state);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

const ACTIVE_STATES = new Set(["connecting", "running", "stopping"]);
const ACTIVE_INTERVAL = 1000;
const IDLE_INTERVAL = 5000;
const OFFLINE_INTERVAL = 2000;

export const isActive = (status) => Boolean(status && ACTIVE_STATES.has(status.state));

export const session = createStore({ status: null, loaded: false, online: true, error: null });
export const auth = createStore({ status: null, loaded: false, error: null });

let pollTimer = null;
let pollStarted = false;
let sessionRequest = null;

export function refreshSession() {
  if (!sessionRequest) {
    sessionRequest = api
      .session()
      .then((status) => session.set({ status, loaded: true, online: true, error: null }))
      .catch((error) => session.set((previous) => ({ ...previous, loaded: true, online: error.status !== 0, error })))
      .finally(() => {
        sessionRequest = null;
      });
  }
  return sessionRequest;
}

function scheduleNext(elapsed = 0) {
  clearTimeout(pollTimer);
  const { status, online } = session.get();
  const interval = !online ? OFFLINE_INTERVAL : isActive(status) ? ACTIVE_INTERVAL : IDLE_INTERVAL;
  pollTimer = setTimeout(poll, Math.max(200, interval - elapsed));
}

async function poll() {
  const startedAt = performance.now();
  await refreshSession();
  scheduleNext(performance.now() - startedAt);
}

/** 1 s while connecting, running or stopping; 5 s otherwise. */
export function startSessionPolling() {
  if (pollStarted) return;
  pollStarted = true;
  poll();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });
}

/** Adopt a status returned by start or stop without waiting for the next poll. */
export function applySession(status) {
  session.set({ status, loaded: true, online: true, error: null });
  scheduleNext();
}

let authRequest = null;

export function refreshAuth() {
  if (!authRequest) {
    authRequest = api
      .auth()
      .then((status) => auth.set({ status, loaded: true, error: null }))
      .catch((error) => auth.set((previous) => ({ ...previous, loaded: true, error })))
      .finally(() => {
        authRequest = null;
      });
  }
  return authRequest;
}

export function applyAuth(status) {
  auth.set({ status, loaded: true, error: null });
}
