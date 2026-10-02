// Dashboard: the deck (state, progress, transport), readouts, worker lanes, channels, last session.

import { api } from "../api.js";
import { requestStop } from "../actions.js";
import { clear, fileName, h, icon, setAttr, setChildren, setText } from "../dom.js";
import { fmtDateTime, fmtDecimal, fmtDuration, fmtInt, fmtRelative, fmtSize, MISSING, plural, workerIndex, workerTag } from "../format.js";
import { applySession, isActive, refreshSession, session } from "../store.js";
import { button, callout, empty, eqGlyph, keycap, linkButton, panel, skeleton, stateBadge, toast, transport, withBusy } from "../ui.js";

const BAR_COUNT = 96;
const DANCE_BARS = 5;

// Waveform meter ------------------------------------------------------------------

function generator(seed) {
  let state = seed;
  return () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
}

// Loudness contour of the meter: quiet intro, two builds, a breakdown, an outro.
const ENVELOPE = [0.3, 0.42, 0.7, 0.92, 0.98, 0.72, 0.38, 0.3, 0.52, 0.86, 1, 0.94, 0.6, 0.74, 0.96, 0.82, 0.5, 0.3];

/** Fixed pseudo-random bar heights that read as an audio waveform. */
function waveform(count) {
  const random = generator(20261003);
  const heights = [];
  for (let index = 0; index < count; index += 1) {
    const position = (index / (count - 1)) * (ENVELOPE.length - 1);
    const left = Math.floor(position);
    const right = Math.min(ENVELOPE.length - 1, left + 1);
    const mix = position - left;
    const loudness = ENVELOPE[left] * (1 - mix) + ENVELOPE[right] * mix;
    heights.push(Math.min(1, Math.max(0.14, loudness * (0.5 + 0.5 * random()))));
  }
  return heights;
}

function createMeter() {
  const heights = waveform(BAR_COUNT);
  const random = generator(7);
  const timing = heights.map(() => ({ t: `${(0.6 + random() * 0.5).toFixed(2)}s`, d: `${(-random()).toFixed(2)}s` }));
  const bars = () =>
    heights.map((height, index) => h("i", { style: { "--h": height.toFixed(3), "--t": timing[index].t, "--d": timing[index].d } }));
  const base = bars();
  const fill = bars();
  const el = h(
    "div",
    { class: "meter", role: "progressbar", "aria-label": "Session progress", "aria-valuemin": "0", "aria-valuemax": "100", "data-mode": "rest" },
    h("div", { class: "meter-bars" }, base),
    h("div", { class: "meter-clip" }, h("div", { class: "meter-clip-inner" }, h("div", { class: "meter-bars meter-fill" }, fill))),
    h("div", { class: "meter-head" }),
  );
  let dancing = [];

  function set({ mode, fraction = 0, live = false, text }) {
    const p = mode === "determinate" ? Math.min(1, Math.max(0, fraction)) : 0;
    setAttr(el, "data-mode", mode);
    setAttr(el, "data-live", live);
    el.style.setProperty("--p", p.toFixed(4));
    setAttr(el, "aria-valuenow", mode === "determinate" ? Math.round(p * 100) : null);
    setAttr(el, "aria-valuetext", text ?? null);

    const head = Math.min(BAR_COUNT - 1, Math.floor(p * BAR_COUNT));
    const next = [];
    if (live && mode === "determinate") {
      for (let index = Math.max(0, head - DANCE_BARS + 1); index <= head; index += 1) next.push(index);
    }
    for (const index of dancing) {
      if (!next.includes(index)) {
        base[index].removeAttribute("data-dance");
        fill[index].removeAttribute("data-dance");
      }
    }
    for (const index of next) {
      if (!dancing.includes(index)) {
        base[index].setAttribute("data-dance", "");
        fill[index].setAttribute("data-dance", "");
      }
    }
    dancing = next;
  }

  return { el, set };
}

// Readouts ------------------------------------------------------------------------

const READOUTS = [
  { key: "completed", label: "Completed", iconName: "check-circle", tone: "ok" },
  { key: "skipped", label: "Skipped", iconName: "skip-forward", tone: "skip" },
  { key: "failed", label: "Failed", iconName: "x-circle", tone: "err" },
  { key: "pending", label: "Pending", iconName: "hourglass-medium", tone: "muted" },
  { key: "size", label: "Downloaded", iconName: "download-simple", tone: "muted" },
  { key: "speed", label: "Speed", iconName: "lightning", tone: "muted" },
  { key: "elapsed", label: "Elapsed", iconName: "timer", tone: "muted" },
  { key: "eta", label: "ETA", iconName: "clock", tone: "muted" },
];

function createReadouts() {
  const cells = {};
  const el = h(
    "dl",
    { class: "readouts", "aria-label": "Session metrics" },
    READOUTS.map((spec) => {
      const label = h("span", null, spec.label);
      const value = h("span", { class: "readout-value" }, MISSING);
      const unit = h("span", { class: "readout-unit" });
      const cell = h("div", { class: "readout" }, h("dt", { "data-tone": spec.tone }, icon(spec.iconName), label), h("dd", null, value, unit));
      cells[spec.key] = { cell, label, value, unit };
      return cell;
    }),
  );
  function set(key, value, unit = "", label) {
    const cell = cells[key];
    setText(cell.value, value);
    setText(cell.unit, unit);
    if (label) setText(cell.label, label);
  }
  return { el, set, cells };
}

// View ------------------------------------------------------------------------------

function runningProgress(status) {
  const progress = status?.progress;
  return progress && progress.status === "running" ? progress : null;
}

const PRIMER = [
  {
    iconName: "broadcast",
    title: "Scan channels in order",
    text: "Each channel is read from its last checkpoint, oldest message first.",
  },
  {
    iconName: "funnel",
    title: "Filter before queueing",
    text: "Type, format, size, date and duration filters decide what gets queued.",
  },
  {
    iconName: "download-simple",
    title: "Download in parallel",
    text: "Workers pull from the queue, and a failed transfer is retried up to three times.",
  },
];

export function mount(root) {
  const page = h("div", { class: "page dash" });

  // Deck
  const badge = stateBadge("idle");
  const context = h("p", { class: "deck-context" });
  const controls = h("div", { class: "deck-controls" });
  const headline = h("p", { class: "deck-display" });
  const count = h("p", { class: "deck-count" });
  const sub = h("p", { class: "deck-sub" });
  const meter = createMeter();
  const alertHost = h("div", { class: "deck-alert" });
  const deck = h(
    "section",
    { class: "deck", "aria-label": "Session" },
    h(
      "div",
      { class: "deck-core" },
      h("div", { class: "deck-glow" }),
      h("div", { class: "deck-top" }, h("div", { class: "deck-status" }, badge.el, context), controls),
      h("div", { class: "deck-figure" }, headline, h("div", { class: "deck-aside" }, count, sub)),
      h("div", null, meter.el, h("div", { class: "meter-scale micro", "aria-hidden": "true" }, ["0", "25", "50", "75", "100"].map((tick) => h("span", null, tick)))),
      alertHost,
    ),
  );

  const readouts = createReadouts();

  // Lanes
  const lanesNote = h("p", { class: "panel-note" });
  const lanesBody = h("div", { class: "lanes" });
  const lanesPanel = h(
    "section",
    { class: "panel", "aria-labelledby": "lanes-title" },
    h("header", { class: "panel-head" }, h("h2", { class: "panel-title", id: "lanes-title" }, "Active downloads"), lanesNote),
    h("div", { class: "panel-body" }, lanesBody),
  );

  // Channels
  const channelsNote = h("p", { class: "panel-note" });
  const channelsBody = h("div", { class: "chan-list" });
  const channelsPanel = h(
    "section",
    { class: "panel", "aria-labelledby": "channels-title" },
    h("header", { class: "panel-head" }, h("h2", { class: "panel-title", id: "channels-title" }, "Channels"), channelsNote),
    h("div", { class: "panel-body" }, channelsBody),
  );

  // Last session
  const summaryBody = h("div");
  const summaryPanel = panel({ title: "Last session", body: summaryBody });

  const columns = h("div", { class: "dash-cols" }, lanesPanel, channelsPanel, summaryPanel);

  const primer = h(
    "section",
    { class: "panel", "aria-label": "How a session runs" },
    h(
      "div",
      { class: "panel-body primer" },
      PRIMER.map((item) =>
        h("div", { class: "primer-item" }, h("div", { class: "empty-icon" }, icon(item.iconName)), h("div", null, h("p", { class: "primer-title" }, item.title), h("p", { class: "primer-text" }, item.text))),
      ),
    ),
  );

  const loading = h(
    "div",
    { class: "page skeleton-wrap", "aria-hidden": "true" },
    h("div", { class: "deck" }, h("div", { class: "deck-core" }, skeleton("7rem", "1.75rem"), skeleton("min(22rem, 70%)", "6rem"), skeleton("100%", "5.5rem"))),
    skeleton("100%", "11rem"),
  );

  // Controls --------------------------------------------------------------------
  const maxInput = h("input", { class: "input num", id: "start-max", inputmode: "numeric", autocomplete: "off", placeholder: "No limit", "aria-describedby": "start-help" });
  const workersInput = h("input", { class: "input num", id: "start-workers", inputmode: "numeric", autocomplete: "off", placeholder: "Default", "aria-describedby": "start-help" });
  const startButton = transport({ kind: "start", label: "Start session", type: "submit" });
  const startForm = h(
    "form",
    { class: "start-form", novalidate: true },
    h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "start-max" }, "Max files"), maxInput),
    h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "start-workers" }, "Workers"), workersInput),
    startButton,
    h("p", { class: "sr-only", id: "start-help" }, "Leave both fields empty to use the configured file limit and worker count. Workers accepts 1 to 20."),
  );
  const optionsLine = h("div", { class: "deck-options" });
  const stopButton = transport({ kind: "stop", label: "Stop session", onClick: () => requestStop() });
  let controlsMode = null;

  function showAlert(node) {
    clear(alertHost);
    if (node) alertHost.append(node);
  }

  function parseOption(input, { min, max, empty: emptyValue }) {
    const text = input.value.trim();
    if (!text) return { value: emptyValue };
    if (!/^\d+$/.test(text)) return { error: true };
    const value = Number(text);
    return value < min || (max !== undefined && value > max) ? { error: true } : { value };
  }

  startForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const maxFiles = parseOption(maxInput, { min: 0, empty: 0 });
    const workers = parseOption(workersInput, { min: 1, max: 20, empty: null });
    setAttr(maxInput, "aria-invalid", maxFiles.error ? "true" : null);
    setAttr(workersInput, "aria-invalid", workers.error ? "true" : null);
    const problems = [];
    if (maxFiles.error) problems.push("Max files must be a whole number, 0 or greater.");
    if (workers.error) problems.push("Workers must be a whole number from 1 to 20.");
    if (problems.length) {
      showAlert(callout({ tone: "err", role: "alert", title: "Check the session options", list: problems }));
      (maxFiles.error ? maxInput : workersInput).focus();
      return;
    }
    withBusy(startButton, async () => {
      try {
        const status = await api.startSession({ max_files: maxFiles.value, workers: workers.value });
        showAlert(null);
        applySession(status);
      } catch (error) {
        if (error.status === 412 || error.code === "not_authorized") {
          showAlert(
            callout({
              tone: "warn",
              role: "alert",
              iconName: "lock-key",
              title: "Sign in to Telegram first",
              text: "The session did not start because this app is not signed in to Telegram. Sign in on the Account page, then start again.",
              actions: linkButton({ label: "Open Account", href: "#/account", iconName: "arrow-right", size: "sm" }),
            }),
          );
        } else if (error.status === 409) {
          toast({ tone: "info", title: "A session is already running" });
          refreshSession();
        } else {
          showAlert(callout({ tone: "err", role: "alert", title: "The session could not start", text: error.message, list: error.details }));
        }
      }
    });
  });

  function renderControls(status) {
    const mode = isActive(status) ? "stop" : "start";
    if (mode !== controlsMode) {
      controlsMode = mode;
      clear(controls);
      if (mode === "start") controls.append(startForm);
      else controls.append(optionsLine, stopButton);
    }
    if (mode === "stop") {
      const stopping = status.state === "stopping";
      stopButton.disabled = stopping;
      setText(stopButton.querySelector(".transport-label"), stopping ? "Stopping" : "Stop session");
      const options = status.options ?? {};
      const progress = runningProgress(status);
      const workers = options.workers ?? progress?.total_workers ?? "default";
      const limit = options.max_files > 0 ? fmtInt(options.max_files) : "none";
      const signature = `${limit}|${workers}`;
      if (optionsLine.dataset.signature !== signature) {
        optionsLine.dataset.signature = signature;
        optionsLine.replaceChildren("File limit", keycap(limit), "Workers", keycap(String(workers)));
      }
    }
  }

  // Deck text ---------------------------------------------------------------------
  let numeral = null;

  /** Big whole percent with the decimal and the unit set small beside it. */
  function setNumeral(percent) {
    const fixed = Math.min(100, Math.max(0, percent)).toFixed(1);
    const [whole, fraction] = fixed === "100.0" ? ["100", ""] : fixed.split(".");
    if (!numeral) {
      numeral = { whole: h("span", { class: "deck-int" }), fraction: h("span", { class: "deck-frac" }) };
      headline.className = "deck-numeral";
      headline.replaceChildren(numeral.whole, h("span", { class: "deck-side" }, numeral.fraction, h("span", { class: "deck-unit" }, "%")));
    }
    setText(numeral.whole, whole);
    setText(numeral.fraction, fraction ? `.${fraction}` : "");
    numeral.fraction.hidden = !fraction;
  }

  function setDisplay(text) {
    if (numeral) {
      numeral = null;
      headline.className = "deck-display";
    }
    setText(headline, text);
  }

  function setCount(done, total, noun) {
    const signature = `${done}|${total}|${noun}`;
    if (count.dataset.signature === signature) return;
    count.dataset.signature = signature;
    if (done === null) count.replaceChildren();
    else if (total === null) count.replaceChildren(h("b", null, fmtInt(done)), ` ${noun}`);
    else count.replaceChildren(h("b", null, fmtInt(done)), " of ", h("b", null, fmtInt(total)), ` ${noun}`);
  }

  function setContext(parts) {
    const signature = parts.map((part) => (typeof part === "string" ? part : part.key)).join("|");
    if (context.dataset.signature === signature) return;
    context.dataset.signature = signature;
    context.replaceChildren(...parts.map((part) => (typeof part === "string" ? part : part.node())));
  }

  function renderDeck(status) {
    const state = status.state;
    const progress = runningProgress(status);
    const summary = status.summary;
    const done = status.channels_done?.length ?? 0;
    badge.set(state);
    setAttr(deck, "data-live", state === "running");

    if (!progress && isActive(status)) {
      // No coordinator numbers yet (connecting) or any more (stopping): the total is unknown.
      const label = { connecting: "Connecting", running: "Starting", stopping: "Stopping" }[state];
      setDisplay(label);
      setCount(null);
      setText(sub, state === "stopping" ? "Cancelling active downloads. Finished files are kept." : "Opening the Telegram session and resolving the configured channels.");
      setContext(["Started ", { key: status.started_at ?? "", node: () => h("span", { class: "mono" }, fmtDateTime(status.started_at)) }]);
      meter.set({ mode: "indeterminate", text: label });
      return;
    }

    if (progress) {
      setNumeral(progress.progress_percentage);
      setCount(progress.terminal_tasks, progress.total_tasks, plural(progress.total_tasks, "file"));
      if (state === "stopping") {
        setText(sub, "Cancelling active downloads. Finished files are kept.");
      } else {
        setText(sub, `${fmtInt(progress.pending_tasks)} pending, ${progress.active_workers} of ${progress.total_workers} workers busy`);
      }
      const total = status.total_channels || 0;
      if (status.current_channel) {
        const position = total ? `${Math.min(done + 1, total)} / ${total}` : "";
        setContext([
          "Scanning",
          { key: status.current_channel, node: () => h("span", { class: "mono" }, status.current_channel) },
          { key: position, node: () => (position ? keycap(position) : "") },
        ]);
      } else if (total && done >= total) {
        setContext([`All ${total} ${plural(total, "channel")} scanned, finishing queued downloads`]);
      } else {
        setContext(["Preparing the next channel"]);
      }
      meter.set({ mode: "determinate", fraction: progress.progress_percentage / 100, live: state === "running" });
      return;
    }

    if (summary) {
      const terminal = summary.files_completed + summary.files_skipped + summary.files_failed;
      const percent = summary.files_queued ? (terminal / summary.files_queued) * 100 : state === "finished" ? 100 : 0;
      setNumeral(percent);
      setCount(summary.files_completed, null, `${plural(summary.files_completed, "file")} downloaded`);
      const when = status.finished_at ? fmtRelative(status.finished_at) : "";
      if (state === "finished") setText(sub, `Finished ${when} in ${fmtDuration(summary.session_duration_seconds)}.`);
      else if (state === "stopped") setText(sub, `Stopped ${when}. The next session resumes after the last fully processed message.`);
      else setText(sub, `Ended ${when} after ${fmtDuration(summary.session_duration_seconds)}.`);
      setContext(status.finished_at ? ["Last run", { key: status.finished_at, node: () => h("span", { class: "mono" }, fmtDateTime(status.finished_at)) }] : []);
      meter.set({ mode: percent > 0 ? "determinate" : "rest", fraction: percent / 100 });
      return;
    }

    setDisplay(state === "failed" ? "Failed" : "Ready");
    setCount(null);
    setText(sub, state === "failed" ? "The session ended before any file was processed." : "Scans your channels in order and downloads every new file that passes the filters.");
    setContext(state === "failed" && status.finished_at ? ["Last attempt", { key: status.finished_at, node: () => h("span", { class: "mono" }, fmtDateTime(status.finished_at)) }] : ["No session is running"]);
    meter.set({ mode: "rest" });
  }

  let errorSignature = "";

  function renderError(status) {
    const error = status.state === "failed" ? status.error : null;
    const signature = error ? `${error.code}|${error.message}` : "";
    if (signature === errorSignature) return;
    errorSignature = signature;
    if (!error) {
      showAlert(null);
    } else if (error.code === "not_authorized") {
      showAlert(
        callout({
          tone: "warn",
          iconName: "lock-key",
          title: "Telegram is not signed in",
          text: error.message || "Sign in on the Account page, then start the session again.",
          actions: linkButton({ label: "Open Account", href: "#/account", iconName: "arrow-right", size: "sm" }),
        }),
      );
    } else {
      showAlert(callout({ tone: "err", title: "The session failed", text: error.message || "The server did not report a reason. See the Logs view." }));
    }
  }

  // Readouts ------------------------------------------------------------------------
  function renderReadouts(status) {
    const progress = runningProgress(status);
    const summary = status.summary;
    if (progress) {
      const size = fmtSize(progress.total_mb_downloaded);
      readouts.set("completed", fmtInt(progress.completed_tasks));
      readouts.set("skipped", fmtInt(progress.skipped_tasks));
      readouts.set("failed", fmtInt(progress.failed_tasks));
      readouts.set("pending", fmtInt(progress.pending_tasks), "", "Pending");
      readouts.set("size", size.value, size.unit);
      readouts.set("speed", fmtDecimal(progress.download_speed_mbpm), "MB/min", "Speed");
      readouts.set("elapsed", fmtDuration(progress.elapsed_time_seconds), "", "Elapsed");
      readouts.set("eta", fmtDuration(progress.estimated_time_remaining), "", "ETA");
      setAttr(readouts.cells.failed.cell, "data-flag", progress.failed_tasks > 0 ? "err" : null);
    } else if (summary && !isActive(status)) {
      const size = fmtSize(summary.total_mb_downloaded);
      const terminal = summary.files_completed + summary.files_skipped + summary.files_failed;
      readouts.set("completed", fmtInt(summary.files_completed));
      readouts.set("skipped", fmtInt(summary.files_skipped));
      readouts.set("failed", fmtInt(summary.files_failed));
      readouts.set("pending", fmtInt(Math.max(0, summary.files_queued - terminal)), "", "Not processed");
      readouts.set("size", size.value, size.unit);
      readouts.set("speed", fmtDecimal(summary.average_speed_mbpm), "MB/min", "Avg speed");
      readouts.set("elapsed", fmtDuration(summary.session_duration_seconds), "", "Duration");
      readouts.set("eta", fmtDecimal(summary.success_rate), "%", "Success rate");
      setAttr(readouts.cells.failed.cell, "data-flag", summary.files_failed > 0 ? "err" : null);
    } else {
      for (const spec of READOUTS) readouts.set(spec.key, spec.key === "elapsed" || spec.key === "eta" ? "--:--" : MISSING, "", spec.label);
      setAttr(readouts.cells.failed.cell, "data-flag", null);
    }
  }

  // Lanes ---------------------------------------------------------------------------
  let lanes = [];

  function renderLanes(status) {
    const progress = runningProgress(status);
    if (!progress) {
      if (lanes.length || !lanesBody.firstChild) {
        lanes = [];
        lanesBody.replaceChildren(empty({ iconName: "cpu", title: "Workers are starting", text: "Each lane shows the file a worker is downloading." }));
      }
      setText(lanesNote, "");
      return;
    }
    const active = progress.active_downloads ?? [];
    const total = Math.max(progress.total_workers ?? 0, active.length);
    if (lanes.length !== total) {
      lanes = Array.from({ length: total }, (_, index) => {
        const el = h("div", { class: "lane" });
        return { el, signature: null, index: index + 1 };
      });
      lanesBody.replaceChildren(...lanes.map((lane) => lane.el));
    }
    const byIndex = new Map();
    const loose = [];
    for (const item of active) {
      const index = workerIndex(item.worker_id);
      if (index !== null && index >= 1 && index <= total && !byIndex.has(index)) byIndex.set(index, item);
      else loose.push(item);
    }
    for (const lane of lanes) {
      const item = byIndex.get(lane.index) ?? (byIndex.has(lane.index) ? null : loose.shift()) ?? null;
      const signature = item ? `${item.worker_id}|${item.filename}|${item.file_size_mb}` : "idle";
      if (signature === lane.signature) continue;
      lane.signature = signature;
      setAttr(lane.el, "data-idle", !item);
      const tag = keycap(item ? workerTag(item.worker_id) : `W${lane.index}`);
      if (item) lane.el.replaceChildren(tag, eqGlyph(true), fileName(item.filename), h("span", { class: "lane-size mono num" }, `${fmtDecimal(item.file_size_mb)} MB`));
      else lane.el.replaceChildren(tag, eqGlyph(false), h("span", { class: "lane-idle" }, status.state === "stopping" ? "Stopped" : "Waiting for a file"), h("span"));
    }
    setText(lanesNote, `${active.length} of ${total} busy`);
  }

  // Channels -------------------------------------------------------------------------
  let channelsSignature = null;

  function stat(value, label) {
    return h("span", { class: "stat" }, h("b", null, fmtInt(value)), h("span", { class: "micro" }, label));
  }

  function renderChannels(status) {
    const done = status.channels_done ?? [];
    const current = status.current_channel;
    const active = isActive(status);
    const remaining = Math.max(0, (status.total_channels ?? 0) - done.length - (current ? 1 : 0));
    const signature = JSON.stringify([done.map((item) => [item.channel_name, item.files_queued, item.files_found, item.messages_processed]), current, remaining, active, status.state]);
    if (signature === channelsSignature) return;
    channelsSignature = signature;

    const rows = done.map((item) =>
      h(
        "div",
        { class: "chan" },
        h("span", { class: "chan-glyph", "data-tone": "ok" }, icon("check-bold", { size: "0.875rem" })),
        h("div", { class: "chan-main" }, h("span", { class: "chan-title" }, item.channel_title || item.channel_name), h("span", { class: "chan-id mono" }, item.channel_name)),
        h("div", { class: "chan-stats" }, stat(item.files_queued, "queued"), stat(item.files_found, "found"), stat(item.messages_processed, "messages")),
      ),
    );
    if (current) {
      rows.push(
        h(
          "div",
          { class: "chan" },
          h("span", { class: "chan-glyph", "data-tone": "ok" }, eqGlyph(status.state === "running")),
          h("div", { class: "chan-main" }, h("span", { class: "chan-title mono" }, current), h("span", { class: "chan-id" }, "Reading messages")),
          h("span", { class: "chan-state", "data-tone": "ok" }, "Scanning"),
        ),
      );
    }
    if (remaining > 0) {
      const waiting = active && status.state !== "stopping";
      rows.push(
        h(
          "div",
          { class: "chan" },
          h("span", { class: "chan-glyph", "data-tone": "muted" }, icon(waiting ? "clock" : "prohibit")),
          h(
            "div",
            { class: "chan-main" },
            h("span", { class: "chan-title" }, `${remaining} more ${plural(remaining, "channel")}`),
            h("span", { class: "chan-id" }, waiting ? "Scanned after the current one" : "Not reached in this session"),
          ),
          h("span", { class: "chan-state", "data-tone": "muted" }, waiting ? "Waiting" : "Skipped"),
        ),
      );
    }
    if (!rows.length) {
      channelsBody.replaceChildren(
        empty({ iconName: "broadcast", title: "No channels scanned yet", text: "Channels are scanned one after another once the session connects." }),
      );
    } else {
      channelsBody.replaceChildren(...rows);
    }
    setText(channelsNote, status.total_channels ? `${done.length} of ${status.total_channels} scanned` : "");
  }

  // Last session ------------------------------------------------------------------------
  let summarySignature = null;

  function summaryItem(label, value, unit) {
    return h("div", { class: "summary-item" }, h("dt", { class: "micro" }, label), h("dd", null, value, unit && h("small", null, unit)));
  }

  function renderSummary(status) {
    const summary = status.summary;
    const results = status.results;
    const signature = JSON.stringify([status.state, status.started_at, status.finished_at, summary, results && { ...results, channels_details: undefined }, status.options]);
    if (signature === summarySignature) return;
    summarySignature = signature;
    const options = status.options ?? {};
    const meta = h(
      "p",
      { class: "summary-meta" },
      h("span", null, "Started ", h("b", { class: "num" }, fmtDateTime(status.started_at))),
      h("span", null, "Ended ", h("b", { class: "num" }, fmtDateTime(status.finished_at))),
      h("span", null, "File limit ", h("b", { class: "num" }, options.max_files > 0 ? fmtInt(options.max_files) : "none")),
      h("span", null, "Workers ", h("b", { class: "num" }, options.workers ?? "default")),
    );
    const items = [];
    if (summary) {
      items.push(summaryItem("Queued", fmtInt(summary.files_queued)));
      items.push(summaryItem("Success rate", fmtDecimal(summary.success_rate), "%"));
    }
    if (results) {
      items.push(summaryItem("Channels", fmtInt(results.channels_processed)));
      items.push(summaryItem("Files found", fmtInt(results.total_files_found)));
      items.push(summaryItem("Messages scanned", fmtInt(results.total_messages_processed)));
    }
    setChildren(summaryBody, meta, items.length ? h("dl", { class: "summary-grid" }, items) : null);
  }

  // Layout ---------------------------------------------------------------------------------
  let layout = null;

  function render({ status, loaded }) {
    if (!loaded) {
      if (layout !== "loading") {
        layout = "loading";
        root.replaceChildren(loading);
      }
      return;
    }
    if (!status) {
      if (layout !== "error") {
        layout = "error";
        root.replaceChildren(
          h(
            "div",
            { class: "page" },
            callout({
              tone: "err",
              role: "alert",
              title: "The session status is unavailable",
              text: "The local server did not answer. It is retried automatically every few seconds.",
              actions: button({ label: "Retry now", iconName: "arrow-clockwise", size: "sm", onClick: () => refreshSession() }),
            }),
          ),
        );
      }
      return;
    }

    const active = isActive(status);
    const ended = !active && Boolean(status.summary || status.results);
    const next = active ? "active" : ended ? "ended" : "idle";
    if (layout !== next) {
      const firstPaint = layout === null || layout === "loading" || layout === "error";
      layout = next;
      lanesPanel.hidden = next !== "active";
      summaryPanel.hidden = next !== "ended";
      columns.hidden = next === "idle";
      readouts.el.hidden = next === "idle";
      primer.hidden = next !== "idle";
      if (firstPaint) {
        page.replaceChildren(deck, readouts.el, columns, primer);
        root.replaceChildren(page);
      }
    }
    renderControls(status);
    renderDeck(status);
    renderError(status);
    if (next !== "idle") {
      renderReadouts(status);
      renderChannels(status);
    }
    if (next === "active") renderLanes(status);
    if (next === "ended") renderSummary(status);
  }

  const unsubscribe = session.subscribe(render);
  render(session.get());
  return unsubscribe;
}
