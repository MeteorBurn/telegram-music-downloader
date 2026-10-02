// Logs: live tail with level filter, text search, pause and follow. The pane owns the scroll.

import { clear, h, icon, setAttr, setText } from "../dom.js";
import { fmtClock, fmtInt } from "../format.js";
import { LOG_CAP, logState, startLogs, subscribeLogs } from "../logstream.js";
import { button, eqGlyph, iconButton, keycap } from "../ui.js";

const LEVELS = [
  { key: "DEBUG", label: "Debug", tone: "muted" },
  { key: "INFO", label: "Info", tone: null },
  { key: "WARNING", label: "Warning", tone: "warn" },
  { key: "ERROR", label: "Error", tone: "err" },
];
const STICK_DISTANCE = 32;
const MARKER = /^\s*\[([A-Z][A-Z0-9_]*)\]\s?/;

// View settings survive navigation within the page session.
const prefs = { levels: new Set(LEVELS.map((level) => level.key)), query: "", follow: true };

const levelKey = (level) => (level === "CRITICAL" ? "ERROR" : level === "WARN" ? "WARNING" : level);

/** Splits leading [MARKER] tags from the rest of a log message. */
function parseMessage(message) {
  const tags = [];
  let rest = String(message ?? "");
  for (let guard = 0; guard < 3; guard += 1) {
    const match = MARKER.exec(rest);
    if (!match) break;
    tags.push(match[1]);
    rest = rest.slice(match[0].length);
  }
  return { tags, rest };
}

function highlight(text, query) {
  if (!query) return [text];
  const nodes = [];
  const haystack = text.toLowerCase();
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(query, from);
    if (at === -1) break;
    if (at > from) nodes.push(text.slice(from, at));
    nodes.push(h("mark", null, text.slice(at, at + query.length)));
    from = at + query.length;
  }
  nodes.push(text.slice(from));
  return nodes;
}

export function mount(root) {
  let paused = false;
  let pausedCount = 0;
  let frame = 0;

  const search = h("input", {
    class: "input",
    type: "search",
    id: "log-search",
    placeholder: "Search messages and markers",
    autocomplete: "off",
    spellcheck: "false",
    "aria-label": "Search log lines",
    value: prefs.query,
  });
  const chips = LEVELS.map((level) => {
    const total = h("span", { class: "chip-count num" }, "0");
    const chip = h(
      "button",
      { class: "chip-toggle", type: "button", "data-tone": level.tone, "data-level": level.key, "aria-pressed": String(prefs.levels.has(level.key)) },
      level.label,
      total,
    );
    return { ...level, chip, total };
  });
  const status = h("span", { class: "state-badge", role: "status" });
  const lineCount = h("span", { class: "logs-count mono num" });
  const pauseButton = iconButton({ label: "Pause the live view", iconName: "pause", outlined: true, onClick: togglePause });
  const followButton = iconButton({ label: "Follow new lines", iconName: "arrow-line-down", outlined: true, onClick: () => setFollow(!prefs.follow, true) });

  const pane = h("div", { class: "log-pane", role: "log", "aria-live": "off", "aria-label": "Session log", tabindex: "0" });
  const emptyHost = h("div", { class: "log-empty" });
  const jump = button({ label: "Jump to latest", iconName: "arrow-down", size: "sm", attrs: { hidden: true }, onClick: () => setFollow(true, true) });
  jump.classList.add("jump");

  const view = h(
    "div",
    { class: "logs" },
    h(
      "div",
      { class: "logs-toolbar" },
      h("div", { class: "input-wrap logs-search", "data-prefix": true }, h("span", { class: "input-prefix" }, icon("magnifying-glass")), search, keycap("/")),
      h("div", { class: "logs-levels", role: "group", "aria-label": "Levels" }, chips.map((item) => item.chip)),
      h("div", { class: "logs-controls" }, lineCount, status, pauseButton, followButton),
    ),
    h("div", { class: "log-frame" }, pane, emptyHost, jump),
  );
  root.append(view);

  // Rendering -----------------------------------------------------------------------
  const query = () => prefs.query.trim().toLowerCase();

  function matches(entry, needle) {
    if (entry.divider) return true;
    if (!prefs.levels.has(levelKey(entry.level))) return false;
    return !needle || String(entry.message).toLowerCase().includes(needle);
  }

  function row(entry, needle) {
    if (entry.divider) return h("div", { class: "log-divider" }, entry.message);
    const { tags, rest } = parseMessage(entry.message);
    return h(
      "div",
      { class: "log-row", "data-level": entry.level, "data-id": entry.id },
      h("span", { class: "log-time" }, fmtClock(entry.ts)),
      h("span", { class: "log-level" }, entry.level),
      h(
        "span",
        { class: "log-msg" },
        tags.map((tag) => h("span", { class: "log-tag", "data-tag": tag.startsWith("WORKER") ? "WORKER" : tag, "data-marker": tag }, tag)),
        highlight(rest, needle),
      ),
    );
  }

  function scrollToEnd() {
    pane.scrollTop = pane.scrollHeight;
  }

  function renderCounts() {
    const totals = Object.fromEntries(LEVELS.map((level) => [level.key, 0]));
    let lines = 0;
    for (const entry of logState.entries) {
      if (entry.divider) continue;
      lines += 1;
      const key = levelKey(entry.level);
      if (key in totals) totals[key] += 1;
    }
    for (const item of chips) setText(item.total, fmtInt(totals[item.key]));
    setText(lineCount, `${fmtInt(lines)} of ${fmtInt(LOG_CAP)} lines`);
  }

  function renderEmpty() {
    const hasRows = pane.childElementCount > 0;
    clear(emptyHost);
    if (hasRows) return;
    const filtered = logState.entries.length > 0;
    const loading = logState.status === "loading";
    emptyHost.append(
      h(
        "div",
        { class: "empty" },
        h("div", { class: "empty-icon" }, icon(filtered ? "funnel" : "terminal-window")),
        h("p", { class: "empty-title" }, loading ? "Loading the log" : filtered ? "No lines match the filters" : "No log lines yet"),
        h("p", { class: "empty-text" }, loading ? "Fetching the latest 500 lines." : filtered ? "Widen the level filter or clear the search." : "Lines appear here as soon as a session starts."),
        filtered && !loading
          ? button({ label: "Clear filters", iconName: "x", size: "sm", onClick: clearFilters })
          : null,
      ),
    );
  }

  function renderAll() {
    const needle = query();
    const fragment = document.createDocumentFragment();
    for (const entry of logState.entries) {
      if (matches(entry, needle)) fragment.append(row(entry, needle));
    }
    pane.replaceChildren(fragment);
    renderCounts();
    renderEmpty();
    if (prefs.follow) scrollToEnd();
  }

  function appendEntries(entries) {
    const needle = query();
    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      if (matches(entry, needle)) fragment.append(row(entry, needle));
    }
    const had = pane.childElementCount;
    pane.append(fragment);
    // The pane never holds more than the cap, whatever the filters show.
    while (pane.childElementCount > LOG_CAP) pane.firstElementChild.remove();
    renderCounts();
    if (!had || !pane.childElementCount) renderEmpty();
    if (prefs.follow) scrollToEnd();
  }

  function renderStatus() {
    const map = {
      loading: { tone: "muted", label: "Loading", glyph: () => icon("circle-notch", { cls: "spin" }) },
      live: { tone: "ok", label: "Live", glyph: () => eqGlyph(true) },
      reconnecting: { tone: "warn", label: "Reconnecting", glyph: () => icon("circle-notch", { cls: "spin" }) },
      offline: { tone: "err", label: "Offline", glyph: () => icon("wifi-slash") },
      idle: { tone: "muted", label: "Idle", glyph: () => icon("circle") },
    };
    const meta = paused
      ? { tone: "info", label: pausedCount ? `Paused, ${fmtInt(pausedCount)} new` : "Paused", glyph: () => icon("pause-fill") }
      : map[logState.status] ?? map.idle;
    const signature = `${meta.tone}|${meta.label}`;
    if (status.dataset.signature === signature) return;
    status.dataset.signature = signature;
    status.dataset.tone = meta.tone;
    status.replaceChildren(meta.glyph(), meta.label);
  }

  // Controls ------------------------------------------------------------------------
  function setFollow(next, scroll) {
    prefs.follow = next;
    setAttr(followButton, "aria-pressed", String(next));
    jump.hidden = next;
    if (next && scroll) scrollToEnd();
  }

  function togglePause() {
    paused = !paused;
    setAttr(pauseButton, "aria-pressed", String(paused));
    const label = paused ? "Resume the live view" : "Pause the live view";
    pauseButton.setAttribute("aria-label", label);
    pauseButton.setAttribute("title", label);
    pauseButton.replaceChildren(icon(paused ? "play" : "pause"));
    if (!paused) {
      pausedCount = 0;
      renderAll();
    }
    renderStatus();
  }

  function clearFilters() {
    prefs.query = "";
    search.value = "";
    prefs.levels = new Set(LEVELS.map((level) => level.key));
    for (const item of chips) item.chip.setAttribute("aria-pressed", "true");
    renderAll();
  }

  search.addEventListener("input", () => {
    prefs.query = search.value;
    renderAll();
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && search.value) {
      event.preventDefault();
      search.value = "";
      prefs.query = "";
      renderAll();
    }
  });
  for (const item of chips) {
    item.chip.addEventListener("click", () => {
      if (prefs.levels.has(item.key)) prefs.levels.delete(item.key);
      else prefs.levels.add(item.key);
      item.chip.setAttribute("aria-pressed", String(prefs.levels.has(item.key)));
      renderAll();
    });
  }
  // A marker tag is a shortcut for searching that marker.
  pane.addEventListener("click", (event) => {
    const tag = event.target.closest(".log-tag");
    if (!tag) return;
    prefs.query = `[${tag.dataset.marker}]`;
    search.value = prefs.query;
    renderAll();
  });
  pane.addEventListener(
    "scroll",
    () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const atEnd = pane.scrollHeight - pane.scrollTop - pane.clientHeight < STICK_DISTANCE;
        if (atEnd !== prefs.follow) setFollow(atEnd, false);
      });
    },
    { passive: true },
  );

  function onKey(event) {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
    event.preventDefault();
    search.focus();
    search.select();
  }
  document.addEventListener("keydown", onKey);

  const unsubscribe = subscribeLogs((event) => {
    if (event.type === "status") {
      renderStatus();
      renderEmpty();
    } else if (paused) {
      if (event.type === "append") pausedCount += event.entries.length;
      renderCounts();
      renderStatus();
    } else if (event.type === "append") {
      appendEntries(event.entries);
    } else {
      renderAll();
    }
  });

  setFollow(prefs.follow, false);
  pauseButton.setAttribute("aria-pressed", "false");
  renderStatus();
  renderAll();
  startLogs();

  return () => {
    unsubscribe();
    document.removeEventListener("keydown", onKey);
    if (frame) cancelAnimationFrame(frame);
  };
}
