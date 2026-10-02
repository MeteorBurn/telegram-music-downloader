// Shell: hash router, global status chips, session dock and theme switch.

import { clear, h, icon, prefersReducedMotion, setAttr, setText } from "./dom.js";
import { fmtDecimal, fmtInt } from "./format.js";
import { auth, isActive, refreshAuth, session, startSessionPolling } from "./store.js";
import { announce, button, callout, eqGlyph, iconButton, sessionMeta, stateBadge, transport } from "./ui.js";
import { requestStop } from "./actions.js";

const ROUTES = {
  dashboard: { title: "Dashboard", load: () => import("./views/dashboard.js") },
  library: { title: "Library", load: () => import("./views/library.js") },
  logs: { title: "Logs", load: () => import("./views/logs.js"), fill: true },
  settings: { title: "Settings", load: () => import("./views/settings.js") },
  account: { title: "Account", load: () => import("./views/account.js") },
  kit: { title: "Kit", load: () => import("./views/kit.js") },
};
const DEFAULT_ROUTE = "dashboard";
const THEME_KEY = "tmd-theme";

const root = document.documentElement;
const view = document.getElementById("view");
const titleElement = document.getElementById("view-title");
const dock = document.getElementById("dock");
const statusHost = document.getElementById("topbar-status");

let currentRoute = null;
let currentCleanup = null;
let navigation = 0;

// Router -------------------------------------------------------------------------

function routeFromHash() {
  const name = window.location.hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return ROUTES[name] ? name : null;
}

async function navigate() {
  const name = routeFromHash();
  if (!name) {
    window.history.replaceState(null, "", `#/${DEFAULT_ROUTE}`);
    return navigate();
  }
  if (name === currentRoute) return undefined;

  const first = currentRoute === null;
  const token = ++navigation;
  const route = ROUTES[name];
  if (currentCleanup) currentCleanup();
  currentCleanup = null;
  currentRoute = name;

  setText(titleElement, route.title);
  document.title = `${route.title} - Music Downloader`;
  for (const link of document.querySelectorAll("[data-route]")) {
    setAttr(link, "aria-current", link.dataset.route === name ? "page" : null);
  }
  setAttr(view, "data-fill", route.fill ? "true" : null);
  clear(view);
  view.scrollTop = 0;
  renderDock(session.get().status);

  try {
    const module = await route.load();
    if (token !== navigation) return undefined;
    currentCleanup = module.mount(view) ?? null;
  } catch (error) {
    if (token !== navigation) return undefined;
    console.error(error);
    view.append(
      h(
        "div",
        { class: "page" },
        callout({
          tone: "err",
          role: "alert",
          title: "This view could not be loaded",
          text: "A script failed to load from the local server. Check that it is still running, then reload.",
          actions: button({ label: "Reload", iconName: "arrow-clockwise", onClick: () => window.location.reload() }),
        }),
      ),
    );
  }
  if (!first) view.focus({ preventScroll: true });
  return undefined;
}

// Top bar status -------------------------------------------------------------------

const offlineChip = h(
  "span",
  { class: "chip", "data-tone": "err", role: "status", hidden: true },
  h("span", { class: "chip-glyph" }, icon("wifi-slash")),
  h("span", { class: "chip-label" }, "Server offline"),
);

const sessionGlyph = h("span", { class: "chip-glyph" });
const sessionLabel = h("span", { class: "chip-label" });
const sessionValue = h("span", { class: "chip-strong" });
const sessionChip = h("a", { class: "chip", href: "#/dashboard" }, sessionGlyph, sessionLabel, sessionValue);

const authGlyph = h("span", { class: "chip-glyph" });
const authLabel = h("span", { class: "chip-label" });
const authChip = h("a", { class: "chip", href: "#/account" }, authGlyph, authLabel);

const themeButton = iconButton({ label: "Switch to light theme", iconName: "sun", outlined: true, onClick: toggleTheme });

statusHost.append(offlineChip, sessionChip, authChip, themeButton);

function runningProgress(status) {
  const progress = status?.progress;
  return progress && progress.status === "running" ? progress : null;
}

let sessionGlyphState;

function renderSessionChip(status) {
  const state = status?.state ?? null;
  const meta = state ? sessionMeta(state) : { label: "Loading", tone: "muted", glyph: "circle-notch", spin: true };
  if (state !== sessionGlyphState) {
    sessionGlyphState = state;
    sessionChip.dataset.tone = meta.tone;
    sessionGlyph.replaceChildren(meta.eq ? eqGlyph(true) : icon(meta.glyph, { cls: meta.spin ? "spin" : undefined }));
    setText(sessionLabel, meta.label);
  }
  const progress = isActive(status) ? runningProgress(status) : null;
  const value = progress ? `${fmtDecimal(progress.progress_percentage)}%` : "";
  setText(sessionValue, value);
  sessionValue.hidden = !value;
  setAttr(sessionChip, "aria-label", `Session ${meta.label.toLowerCase()}${value ? `, ${value}` : ""}. Open the dashboard.`);
}

function authPresentation({ status, loaded }) {
  if (!loaded) return { tone: "muted", glyph: "circle-notch", spin: true, label: "Checking account" };
  if (!status) return { tone: "err", glyph: "warning-circle", label: "Account unavailable" };
  switch (status.state) {
    case "authorized": {
      const user = status.user ?? {};
      return { tone: "ok", glyph: "user-circle-fill", label: user.first_name || (user.username ? `@${user.username}` : "Signed in") };
    }
    case "unauthorized":
      return { tone: "warn", glyph: "sign-in", label: "Signed out" };
    case "code_sent":
    case "password_needed":
      return { tone: "info", glyph: "key", label: "Sign-in pending" };
    default:
      return {
        tone: "muted",
        glyph: "question",
        label: "Account unknown",
        hint: "Telegram status is not checked while a session is running.",
      };
  }
}

function renderAuthChip(state) {
  const meta = authPresentation(state);
  authChip.dataset.tone = meta.tone;
  authGlyph.replaceChildren(icon(meta.glyph, { cls: meta.spin ? "spin" : undefined }));
  setText(authLabel, meta.label);
  setAttr(authChip, "title", meta.hint ?? null);
  setAttr(authChip, "aria-label", `Telegram account: ${meta.label}. ${meta.hint ?? "Open the account page."}`);
}

function renderServer(online) {
  offlineChip.hidden = online;
  const server = document.getElementById("server");
  server.dataset.online = String(online);
  server.querySelector("use").setAttribute("href", `/static/img/icons.svg#i-${online ? "plugs-connected" : "wifi-slash"}`);
  setText(document.getElementById("server-state"), online ? "Local server online" : "Not responding, retrying");
}

// Dock: the session transport on every view except the dashboard -----------------------

let dockParts = null;

function renderDock(status) {
  const visible = isActive(status) && currentRoute !== "dashboard";
  if (!visible) {
    if (dockParts) {
      dock.hidden = true;
      clear(dock);
      dockParts = null;
    }
    return;
  }
  if (!dockParts) {
    const badge = stateBadge(status.state);
    const percent = h("span", { class: "dock-pct num" });
    const fill = h("span", { class: "dock-line-fill" });
    const meta = h("span", { class: "dock-meta mono" });
    const stop = transport({ kind: "stop", label: "Stop", size: "sm", onClick: () => requestStop() });
    dock.setAttribute("role", "region");
    dock.setAttribute("aria-label", "Active session");
    dock.append(
      h("a", { class: "dock-main", href: "#/dashboard", "aria-label": "Open the dashboard" }, badge.el, percent, h("span", { class: "dock-line" }, fill), meta),
      stop,
    );
    dock.hidden = false;
    dockParts = { badge, percent, fill, meta, stop };
  }
  const progress = runningProgress(status);
  dockParts.badge.set(status.state);
  setText(dockParts.percent, progress ? `${fmtDecimal(progress.progress_percentage)}%` : "");
  dockParts.fill.style.setProperty("--p", progress ? (progress.progress_percentage / 100).toFixed(4) : "0");
  setText(dockParts.meta, progress ? `${fmtInt(progress.terminal_tasks)} / ${fmtInt(progress.total_tasks)} files` : "");
  dockParts.stop.disabled = status.state === "stopping";
}

// Theme ----------------------------------------------------------------------------------

function renderThemeButton() {
  const dark = root.dataset.theme !== "light";
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  themeButton.setAttribute("aria-label", label);
  themeButton.setAttribute("title", label);
  themeButton.replaceChildren(icon(dark ? "sun" : "moon"));
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute("content", getComputedStyle(document.body).backgroundColor);
}

function toggleTheme() {
  const next = root.dataset.theme === "light" ? "dark" : "light";
  const apply = () => {
    root.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (error) {
      // The choice still applies for this page load.
    }
    renderThemeButton();
  };
  if (!document.startViewTransition || prefersReducedMotion()) {
    apply();
    return;
  }
  // Circular reveal from the toggle (beui theme-toggle mechanism).
  const box = themeButton.getBoundingClientRect();
  const x = box.left + box.width / 2;
  const y = box.top + box.height / 2;
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  root.style.setProperty("--vt-x", `${x}px`);
  root.style.setProperty("--vt-y", `${y}px`);
  root.style.setProperty("--vt-r", `${radius}px`);
  document.startViewTransition(apply);
}

// Wiring -------------------------------------------------------------------------------

let wasActive = null;
let announcedState = null;

session.subscribe(({ status, online }) => {
  root.dataset.live = String(status?.state === "running");
  renderServer(online);
  renderSessionChip(status);
  renderDock(status);

  // The account status is unknown while a session runs, so refresh it at both edges.
  const active = isActive(status);
  if (wasActive !== null && wasActive !== active) refreshAuth();
  wasActive = active;

  if (status && status.state !== announcedState) {
    if (announcedState !== null) announce(`Session ${sessionMeta(status.state).label.toLowerCase()}`);
    announcedState = status.state;
  }
});

auth.subscribe(renderAuthChip);

document.getElementById("server-host").textContent = window.location.host || "127.0.0.1";
renderSessionChip(null);
renderAuthChip(auth.get());
renderThemeButton();

window.addEventListener("hashchange", navigate);
navigate();
startSessionPolling();
refreshAuth();
