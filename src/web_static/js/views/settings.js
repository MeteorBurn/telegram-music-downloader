// Settings: a form over GET/PUT /api/config with dirty tracking, inline validation and a save bar.

import { api } from "../api.js";
import { h, icon, pathText, setAttr, setText } from "../dom.js";
import { plural } from "../format.js";
import { isActive, session } from "../store.js";
import { button, callout, iconButton, keycap, segmented, skeleton, switchControl, toast, uid, withBusy } from "../ui.js";

const FORMAT_SUGGESTIONS = [".flac", ".wav", ".aiff", ".aif", ".m4a", ".dsf", ".ape", ".wv", ".mp3"];
const TEMPLATE_TOKENS = ["original_name", "message_id", "publish_date", "download_date", "artist", "title", "duration", "file_size", "mime_type"];
const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];

const SECTIONS = [
  {
    id: "telegram",
    title: "Telegram",
    desc: "API credentials from my.telegram.org. They never leave this machine.",
    fields: [
      { path: "telegram.api_id", kind: "number", integer: true, min: 1, width: "sm", label: "API ID", desc: "The numeric app id of your Telegram application." },
      { path: "telegram.api_hash", kind: "secret", label: "API hash", desc: "Write only. Leave it empty to keep the stored hash." },
      { path: "telegram.two_factor_auth", kind: "bool", label: "Two-step verification", desc: "Ask for the cloud password while signing in." },
    ],
  },
  {
    id: "channels",
    title: "Channels",
    desc: "Scanned from top to bottom, one after another.",
    fields: [{ path: "channels", kind: "channels", wide: true, label: "Channel list", desc: "A public @username or a numeric id such as -1001234567890." }],
  },
  {
    id: "download",
    title: "Download",
    desc: "Where files go and how much runs at once.",
    fields: [
      { path: "download.output_dir", kind: "text", mono: true, required: true, label: "Output folder", desc: "Relative paths start at the folder the server was launched from." },
      { path: "download.concurrent_downloads", kind: "number", integer: true, min: 1, max: 20, width: "sm", label: "Workers", desc: "Files downloaded at the same time, 1 to 20." },
      { path: "download.max_files_per_run", kind: "number", integer: true, min: 0, width: "sm", suffix: "files", label: "Files per session", desc: "Stops queueing after this many files. 0 means no limit." },
      { path: "download.max_queue_size", kind: "number", integer: true, min: 1, width: "sm", suffix: "files", label: "Queue size", desc: "The most files that may wait for a worker." },
      { path: "download.timeout_between_messages", kind: "number", min: 0, width: "sm", suffix: "sec", label: "Pause between messages", desc: "Delay between messages while a channel is scanned." },
    ],
  },
  {
    id: "rate",
    title: "Rate limit",
    desc: "Checked before each download attempt and shared by all workers.",
    fields: [
      { path: "download.rate_limit.requests_per_second", kind: "number", min: 0, exclusiveMin: true, width: "sm", suffix: "req/s", label: "Requests per second", desc: "Sustained rate of download attempts." },
      { path: "download.rate_limit.burst_size", kind: "number", integer: true, min: 1, width: "sm", label: "Burst size", desc: "Attempts allowed in a quick burst." },
    ],
  },
  {
    id: "naming",
    title: "Naming",
    desc: "How downloaded files are named on disk.",
    fields: [
      { path: "naming.template", kind: "template", wide: true, required: true, label: "File name template", desc: "The extension is added automatically. Artist, title and duration exist only when Telegram sends audio metadata; without them the name falls back to file_<message id>." },
      { path: "naming.date_format", kind: "dateformat", required: true, label: "Date format", desc: "strftime pattern used by publish_date and download_date." },
      { path: "normalize_track_names", kind: "bool", label: "Normalize track names", desc: "After download, cleans underscores, release markers and trailing ids, and moves mix names to the end." },
    ],
  },
  {
    id: "filters",
    title: "Filters",
    desc: "Checked before a file is queued.",
    fields: [
      { path: "filters.file_types", kind: "checks", label: "File types", desc: "Telegram media kinds to accept.", options: [["audio", "Audio"], ["document", "Document"]] },
      { path: "filters.formats", kind: "tags", wide: true, label: "Formats", desc: "File extensions to accept. Press Enter to add one." },
      { kind: "range", paths: ["filters.size.min_mb", "filters.size.max_mb"], suffix: "MB", label: "File size", desc: "Empty means no limit." },
      { kind: "range", paths: ["filters.duration.min_sec", "filters.duration.max_sec"], suffix: "sec", label: "Track duration", desc: "Empty means no limit. Files without a Telegram duration are probed with ffprobe." },
      { kind: "dates", paths: ["filters.date.from", "filters.date.to"], label: "Message date", desc: "" },
    ],
  },
  {
    id: "logging",
    title: "Logging",
    desc: "What reaches console.log in the output folder.",
    fields: [
      { path: "logging.level", kind: "level", label: "Log level", desc: "Events below this level are not written." },
      { path: "logging.console", kind: "bool", label: "Console output", desc: "Also print the log to the server console." },
    ],
  },
];

const LABELS = {
  "telegram.api_id": "API ID",
  "telegram.api_hash": "API hash",
  "telegram.two_factor_auth": "Two-step verification",
  channels: "Channel list",
  "download.output_dir": "Output folder",
  "download.concurrent_downloads": "Workers",
  "download.max_files_per_run": "Files per session",
  "download.max_queue_size": "Queue size",
  "download.timeout_between_messages": "Pause between messages",
  "download.rate_limit.requests_per_second": "Requests per second",
  "download.rate_limit.burst_size": "Burst size",
  "naming.template": "File name template",
  "naming.date_format": "Date format",
  normalize_track_names: "Normalize track names",
  "filters.file_types": "File types",
  "filters.formats": "Formats",
  "filters.size.min_mb": "Minimum size",
  "filters.size.max_mb": "Maximum size",
  "filters.duration.min_sec": "Minimum duration",
  "filters.duration.max_sec": "Maximum duration",
  "filters.date.from": "Start date",
  "filters.date.to": "End date",
  "logging.level": "Log level",
  "logging.console": "Console output",
};
const PATHS = Object.keys(LABELS);
const fieldPaths = (field) => field.paths ?? [field.path];
// The server writes this key to the base config; everything else goes to local_config.yaml.
const BASE_FILE_PATHS = new Set(["filters.date.from"]);
// Kinds checked while editing, not only on save.
const LIVE_KINDS = new Set(["number", "range", "dates"]);
// After an index click, observer updates within this window are the scroll settling.
const PIN_SETTLE_MS = 400;

// Form state lives at module level so edits survive a trip to another view.
const form = { loaded: false, meta: null, initial: {}, values: {}, errors: {}, rowErrors: {}, general: [] };

const clone = (value) => JSON.parse(JSON.stringify(value));
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const getPath = (object, path) => path.split(".").reduce((node, key) => (node === null || node === undefined ? undefined : node[key]), object);

function setPath(object, path, value) {
  const keys = path.split(".");
  let node = object;
  for (const key of keys.slice(0, -1)) {
    node[key] = node[key] ?? {};
    node = node[key];
  }
  node[keys[keys.length - 1]] = value;
}

function adopt(data) {
  const config = data?.config ?? {};
  const values = {};
  for (const path of PATHS) values[path] = getPath(config, path) ?? null;
  values["telegram.api_hash"] = "";
  form.meta = {
    base_path: data?.base_path ?? "",
    local_path: data?.local_path ?? "",
    local_exists: Boolean(data?.local_exists),
    hash_set: Boolean(config.telegram?.api_hash_set),
    hash_hint: config.telegram?.api_hash_hint ?? "",
  };
  form.initial = values;
  form.values = clone(values);
  form.errors = {};
  form.rowErrors = {};
  form.general = [];
  form.loaded = true;
}

const dirtyPaths = () => PATHS.filter((path) => !same(form.values[path], form.initial[path]));

window.addEventListener("beforeunload", (event) => {
  if (form.loaded && dirtyPaths().length) {
    event.preventDefault();
    event.returnValue = "";
  }
});

// Validation ------------------------------------------------------------------------

function numberProblem(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Enter a number.";
  if (field.integer && !Number.isInteger(value)) return "Use a whole number.";
  if (field.max !== undefined && (value < field.min || value > field.max)) return `Use a whole number from ${field.min} to ${field.max}.`;
  if (field.exclusiveMin && value <= field.min) return `Must be greater than ${field.min}.`;
  if (field.min !== undefined && value < field.min) return `Must be ${field.min} or greater.`;
  return null;
}

/** Client-side checks for one field; the server stays the authority. */
function fieldProblems(field, { partial = false } = {}) {
  const errors = {};
  const rowErrors = {};
  const paths = fieldPaths(field);
  const value = form.values[paths[0]];
  if (field.kind === "number") {
    // A box emptied while typing is reported on blur and save, not on every keystroke.
    if (partial && value === "") return { errors, rowErrors };
    const problem = numberProblem(value, field);
    if (problem) errors[field.path] = [problem];
  } else if (field.required && !String(value ?? "").trim()) {
    errors[field.path] = ["This field cannot be empty."];
  } else if (field.kind === "channels") {
    if (!value?.length) errors.channels = ["Add at least one channel."];
    const seen = new Set();
    (value ?? []).forEach((item, index) => {
      const key = String(item).trim();
      if (seen.has(key)) rowErrors[index] = "Duplicate of an earlier row.";
      seen.add(key);
    });
    if (Object.keys(rowErrors).length) errors.channels = ["Remove the duplicate channels."];
  } else if ((field.kind === "checks" || field.kind === "tags") && !value?.length) {
    errors[field.path] = [field.kind === "checks" ? "Select at least one file type." : "Add at least one format."];
  } else if (field.kind === "range" || field.kind === "dates") {
    const [low, high] = paths.map((path) => form.values[path]);
    for (const path of paths) {
      const item = form.values[path];
      if (field.kind === "range" && item !== null && (typeof item !== "number" || !Number.isFinite(item) || item < 0)) {
        errors[path] = ["Enter a number, 0 or greater, or leave it empty."];
      }
    }
    if (!errors[paths[0]] && !errors[paths[1]] && low !== null && high !== null && low > high) {
      errors[paths[0]] = [field.kind === "dates" ? "The start date is after the end date." : "The minimum is greater than the maximum."];
    }
  }
  return { errors, rowErrors };
}

/** Checks for edited fields only. */
function validate(dirty) {
  const errors = {};
  const rowErrors = {};
  const touched = new Set(dirty);
  for (const section of SECTIONS) {
    for (const field of section.fields) {
      if (!fieldPaths(field).some((path) => touched.has(path))) continue;
      const checked = fieldProblems(field);
      Object.assign(errors, checked.errors);
      Object.assign(rowErrors, checked.rowErrors);
    }
  }
  return { errors, rowErrors };
}

function humanize(text) {
  let message = text;
  for (const path of PATHS) {
    if (message.includes(path)) message = message.replace(path, `"${LABELS[path]}"`);
  }
  message = message.charAt(0).toUpperCase() + message.slice(1);
  return /[.!?]$/.test(message) ? message : `${message}.`;
}

/** Maps server detail strings ("download.concurrent_downloads must be ...") to fields. */
function applyServerDetails(details) {
  const errors = {};
  const rowErrors = {};
  const general = [];
  for (const detail of details) {
    const match = /^([A-Za-z_][\w.]*)(?:\[(\d+)\])?\s+(.*)$/.exec(detail);
    const path = match && PATHS.includes(match[1]) ? match[1] : null;
    if (!path) {
      general.push(detail);
      continue;
    }
    const message = humanize(match[3]);
    if (match[2] !== undefined) {
      const index = Number(match[2]);
      if (path === "channels") rowErrors[index] = message;
      (errors[path] = errors[path] ?? []).push(`Row ${index + 1}: ${message}`);
    } else {
      (errors[path] = errors[path] ?? []).push(message);
    }
  }
  form.errors = errors;
  form.rowErrors = rowErrors;
  form.general = general;
}

function buildPayload(dirty) {
  const payload = {};
  for (const path of dirty) {
    let value = form.values[path];
    if (path === "channels") value = value.map((item) => (/^-?\d+$/.test(String(item).trim()) ? Number(item) : String(item).trim()));
    setPath(payload, path, value);
  }
  return payload;
}

// Naming preview ----------------------------------------------------------------------

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const SAMPLE_DATE = new Date(2026, 2, 14, 21, 5, 9);
const SAMPLE = { original_name: "A1. Burial - Archangel", message_id: 48211, file_size: 40265318, mime_type: "audio_flac", artist: "Burial", title: "Archangel", duration: 238 };

function strftime(pattern, date) {
  const pad = (value, width = 2) => String(value).padStart(width, "0");
  const dayOfYear = Math.round((new Date(date.getFullYear(), date.getMonth(), date.getDate()) - new Date(date.getFullYear(), 0, 1)) / 86400000) + 1;
  const codes = {
    Y: date.getFullYear(),
    y: pad(date.getFullYear() % 100),
    m: pad(date.getMonth() + 1),
    d: pad(date.getDate()),
    H: pad(date.getHours()),
    I: pad(date.getHours() % 12 || 12),
    M: pad(date.getMinutes()),
    S: pad(date.getSeconds()),
    f: "000000",
    j: pad(dayOfYear, 3),
    p: date.getHours() < 12 ? "AM" : "PM",
    b: MONTHS[date.getMonth()].slice(0, 3),
    B: MONTHS[date.getMonth()],
    a: DAYS[date.getDay()].slice(0, 3),
    A: DAYS[date.getDay()],
    "%": "%",
  };
  return String(pattern ?? "").replace(/%([A-Za-z%])/g, (match, code) => (code in codes ? String(codes[code]) : match));
}

function previewName(template, dateFormat) {
  const stamp = strftime(dateFormat, SAMPLE_DATE);
  const variables = { ...SAMPLE, publish_date: stamp, download_date: stamp };
  let unknown = null;
  const text = String(template ?? "")
    .replaceAll("{{", "\u0001")
    .replaceAll("}}", "\u0002")
    .replace(/\{([^{}]*)\}/g, (match, body) => {
      const name = body.split(/[!:.[]/)[0].trim();
      if (!name || !(name in variables)) {
        unknown = unknown ?? (name || "{}");
        return "";
      }
      return String(variables[name]);
    });
  if (unknown !== null || /[{}]/.test(text)) return { ok: false, name: `file_${SAMPLE.message_id}.flac`, unknown };
  return { ok: true, name: `${text.replaceAll("\u0001", "{").replaceAll("\u0002", "}")}.flac` };
}

// View --------------------------------------------------------------------------------

export function mount(root) {
  const page = h("div", { class: "page settings" });
  root.append(page);
  let disposed = false;
  let rows = [];
  let indexMarks = [];
  let observer = null;
  let endObserver = null;
  let namingPreview = () => {};

  const saveStatus = h("span", { class: "savebar-status", role: "status" });
  const resetButton = button({ label: "Reset", variant: "ghost", onClick: reset });
  const saveButton = button({ label: "Save changes", iconName: "floppy-disk", variant: "primary", onClick: save });
  const savebar = h("div", { class: "savebar" }, saveStatus, h("div", { class: "savebar-actions" }, keycap("Ctrl S"), resetButton, saveButton));
  const notices = h("div", { class: "settings-notices" });

  function clearError(paths) {
    let changed = false;
    for (const path of paths) {
      if (form.errors[path]) {
        delete form.errors[path];
        changed = true;
      }
    }
    if (paths.includes("channels") && Object.keys(form.rowErrors).length) {
      form.rowErrors = {};
      changed = true;
    }
    return changed;
  }

  /** Records an edit; numeric and range fields are checked right away once they differ from the saved value. */
  function edit(paths, field, { partial = false } = {}) {
    clearError(paths);
    if (field && LIVE_KINDS.has(field.kind) && paths.some((path) => !same(form.values[path], form.initial[path]))) {
      Object.assign(form.errors, fieldProblems(field, { partial }).errors);
    }
    sync();
  }

  // Controls ----------------------------------------------------------------------------
  function textInput(path, { mono, numeric, integer, placeholder, type = "text", label, describedBy }) {
    const id = uid("setting");
    const value = form.values[path];
    const input = h("input", {
      class: "input",
      id,
      type,
      inputmode: numeric ? (integer ? "numeric" : "decimal") : null,
      autocomplete: "off",
      spellcheck: "false",
      placeholder,
      "data-mono": mono || numeric,
      "aria-label": label,
      "aria-describedby": describedBy,
      value: value === null || value === undefined ? "" : String(value),
    });
    return { id, input };
  }

  function parseNumber(text, nullable) {
    const trimmed = text.trim();
    if (!trimmed) return nullable ? null : "";
    return /^-?\d+(\.\d+)?$/.test(trimmed) ? Number(trimmed) : trimmed;
  }

  function wrapInput(input, { suffix, width, action }) {
    return h(
      "div",
      { class: "input-wrap", "data-suffix": Boolean(suffix || action), "data-width": width },
      input,
      suffix && h("span", { class: "input-suffix micro" }, suffix),
      action,
    );
  }

  function buildControl(field, ids) {
    const path = field.path;
    switch (field.kind) {
      case "number":
      case "text": {
        const numeric = field.kind === "number";
        const { id, input } = textInput(path, { mono: field.mono, numeric, integer: field.integer, describedBy: ids.described });
        input.addEventListener("input", () => {
          form.values[path] = numeric ? parseNumber(input.value, false) : input.value;
          edit([path], field, { partial: true });
        });
        if (numeric) input.addEventListener("blur", () => edit([path], field));
        return { el: wrapInput(input, field), labelFor: id, inputs: [input] };
      }
      case "secret": {
        const hint = form.meta.hash_set ? `Stored hash ${form.meta.hash_hint}` : "No hash stored yet";
        const { id, input } = textInput(path, { mono: true, type: "password", placeholder: hint, describedBy: ids.described });
        input.setAttribute("autocomplete", "new-password");
        const reveal = iconButton({ label: "Show the API hash", iconName: "eye", size: "sm" });
        reveal.classList.add("input-action");
        reveal.addEventListener("click", () => {
          const visible = input.type === "text";
          input.type = visible ? "password" : "text";
          const label = visible ? "Show the API hash" : "Hide the API hash";
          reveal.setAttribute("aria-label", label);
          reveal.setAttribute("title", label);
          reveal.replaceChildren(icon(visible ? "eye" : "eye-slash"));
        });
        input.addEventListener("input", () => {
          form.values[path] = input.value.trim();
          edit([path]);
        });
        return { el: wrapInput(input, { action: reveal }), labelFor: id, inputs: [input] };
      }
      case "bool": {
        const id = uid("setting");
        const control = switchControl({
          id,
          checked: form.values[path],
          onChange: (next) => {
            form.values[path] = next;
            edit([path]);
          },
        });
        setAttr(control.el, "aria-describedby", ids.described);
        return { el: control.el, labelFor: id };
      }
      case "level": {
        const control = segmented({
          labelledBy: ids.label,
          options: LOG_LEVELS.map((level) => ({ value: level, label: level })),
          value: form.values[path],
          onChange: (next) => {
            form.values[path] = next;
            edit([path]);
          },
        });
        return { el: control.el };
      }
      case "checks": {
        const el = h(
          "div",
          { class: "check-row", role: "group", "aria-labelledby": ids.label },
          field.options.map(([value, label]) => {
            const input = h("input", { type: "checkbox", checked: (form.values[path] ?? []).includes(value) });
            input.addEventListener("change", () => {
              const selected = new Set(form.values[path] ?? []);
              if (input.checked) selected.add(value);
              else selected.delete(value);
              form.values[path] = field.options.map(([option]) => option).filter((option) => selected.has(option));
              edit([path]);
            });
            return h("label", { class: "check" }, input, h("span", { class: "check-box" }, icon("check-bold")), h("span", null, label));
          }),
        );
        return { el };
      }
      case "tags":
        return tagsControl(field, ids);
      case "channels":
        return channelsControl(field, ids);
      case "range":
      case "dates": {
        const isDate = field.kind === "dates";
        const inputs = field.paths.map((itemPath, index) => {
          const caption = index === 0 ? (isDate ? "From" : "Min") : isDate ? "To" : "Max";
          const { id, input } = textInput(itemPath, { numeric: !isDate, type: isDate ? "date" : "text", placeholder: isDate ? null : "No limit", describedBy: ids.described });
          input.addEventListener("input", () => {
            form.values[itemPath] = isDate ? input.value || null : parseNumber(input.value, true);
            edit(field.paths, field, { partial: true });
          });
          input.addEventListener("blur", () => edit(field.paths, field));
          return { input, block: h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: id }, caption), wrapInput(input, { suffix: field.suffix })) };
        });
        return { el: h("div", { class: "pair", role: "group", "aria-labelledby": ids.label }, inputs.map((item) => item.block)), inputs: inputs.map((item) => item.input) };
      }
      case "template": {
        const { id, input } = textInput(path, { mono: true, describedBy: ids.described });
        const preview = h("span", { class: "mono" });
        const note = h("span");
        namingPreview = () => {
          const result = previewName(form.values["naming.template"], form.values["naming.date_format"]);
          setText(preview, result.name);
          setText(note, result.ok ? "" : result.unknown ? `Unknown field {${result.unknown}}: files would get the fallback name.` : "Unbalanced braces: files would get the fallback name.");
        };
        input.addEventListener("input", () => {
          form.values[path] = input.value;
          namingPreview();
          edit([path]);
        });
        const tokens = h(
          "div",
          { class: "token-list", role: "group", "aria-label": "Insert a field" },
          TEMPLATE_TOKENS.map((token) =>
            h(
              "button",
              {
                class: "token mono",
                type: "button",
                onClick: () => {
                  const start = input.selectionStart ?? input.value.length;
                  const end = input.selectionEnd ?? input.value.length;
                  input.setRangeText(`{${token}}`, start, end, "end");
                  input.focus();
                  input.dispatchEvent(new Event("input"));
                },
              },
              `{${token}}`,
            ),
          ),
        );
        return { el: h("div", null, wrapInput(input, {}), tokens, h("p", { class: "preview" }, "Example", preview, note)), labelFor: id, inputs: [input] };
      }
      case "dateformat": {
        const { id, input } = textInput(path, { mono: true, describedBy: ids.described });
        const example = h("p", { class: "preview" });
        const update = () => example.replaceChildren("Example", h("span", { class: "mono" }, strftime(form.values[path], SAMPLE_DATE)));
        input.addEventListener("input", () => {
          form.values[path] = input.value;
          update();
          namingPreview();
          edit([path]);
        });
        update();
        return { el: h("div", { class: "stack-control" }, wrapInput(input, {}), example), labelFor: id, inputs: [input] };
      }
      default:
        return { el: h("span") };
    }
  }

  function tagsControl(field, ids) {
    const path = field.path;
    const box = h("div", { class: "tags", role: "group", "aria-labelledby": ids.label });
    const input = h("input", { class: "tags-input mono", type: "text", placeholder: "Add a format", autocomplete: "off", spellcheck: "false", "aria-label": "Add a format" });
    const suggestions = h("div", { class: "token-list", role: "group", "aria-label": "Suggested formats" });

    const add = (raw) => {
      const cleaned = raw.trim().replace(/^\.+/, "").toLowerCase();
      if (!cleaned) return;
      const extension = `.${cleaned}`;
      const list = form.values[path] ?? [];
      if (!list.includes(extension)) form.values[path] = [...list, extension];
      render();
      edit([path]);
    };
    const remove = (extension) => {
      form.values[path] = (form.values[path] ?? []).filter((item) => item !== extension);
      render();
      edit([path]);
      input.focus();
    };
    function render() {
      const list = form.values[path] ?? [];
      // The input stays in place so it keeps focus while tags change around it.
      for (const tag of box.querySelectorAll(".tag")) tag.remove();
      input.before(
        ...list.map((extension) =>
          h("span", { class: "tag mono" }, extension, h("button", { class: "tag-x", type: "button", "aria-label": `Remove ${extension}`, onClick: () => remove(extension) }, icon("x-bold"))),
        ),
      );
      const missing = FORMAT_SUGGESTIONS.filter((extension) => !list.includes(extension));
      suggestions.replaceChildren(...missing.map((extension) => h("button", { class: "token mono", type: "button", onClick: () => add(extension) }, `+ ${extension}`)));
      suggestions.hidden = !missing.length;
    }
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === "," || event.key === " ") {
        event.preventDefault();
        add(input.value);
        input.value = "";
      } else if (event.key === "Backspace" && !input.value) {
        const list = form.values[path] ?? [];
        if (list.length) remove(list[list.length - 1]);
      }
    });
    input.addEventListener("blur", () => {
      if (input.value.trim()) {
        add(input.value);
        input.value = "";
      }
    });
    box.addEventListener("click", (event) => {
      if (event.target === box) input.focus();
    });
    box.append(input);
    render();
    return { el: h("div", null, box, suggestions), invalidTarget: box };
  }

  function channelsControl(field, ids) {
    const path = field.path;
    const list = h("ol", { class: "list-editor", "aria-labelledby": ids.label });
    const input = h("input", { class: "input", type: "text", "data-mono": true, placeholder: "@channel or -1001234567890", autocomplete: "off", spellcheck: "false", "aria-label": "Channel to add" });
    const addButton = button({ label: "Add channel", iconName: "plus", variant: "secondary", onClick: add });

    function move(index, delta) {
      const next = [...form.values[path]];
      const target = index + delta;
      [next[index], next[target]] = [next[target], next[index]];
      form.values[path] = next;
      render();
      edit([path]);
      const moved = list.children[target];
      (moved?.querySelector(`[data-action="${delta < 0 ? "up" : "down"}"]:not(:disabled)`) ?? moved?.querySelector("[data-action]:not(:disabled)"))?.focus();
    }
    function remove(index) {
      form.values[path] = form.values[path].filter((_, position) => position !== index);
      render();
      edit([path]);
      (list.children[Math.min(index, list.children.length - 1)]?.querySelector('[data-action="remove"]') ?? input).focus();
    }
    function add() {
      const text = input.value.trim();
      if (!text) {
        input.focus();
        return;
      }
      const value = /^-?\d+$/.test(text) ? Number(text) : text;
      form.values[path] = [...(form.values[path] ?? []), value];
      input.value = "";
      render();
      edit([path]);
      input.focus();
    }
    function render() {
      const values = form.values[path] ?? [];
      list.replaceChildren(
        ...values.map((value, index) =>
          h(
            "li",
            { class: "list-row", "data-invalid": form.rowErrors[index] ? "true" : null, title: form.rowErrors[index] },
            h("span", { class: "list-index mono num" }, index + 1),
            h("span", { class: "list-value mono" }, String(value)),
            h(
              "span",
              { class: "list-actions" },
              iconButton({ label: `Move ${value} up`, iconName: "arrow-up", size: "sm", onClick: () => move(index, -1), attrs: { disabled: index === 0, "data-action": "up" } }),
              iconButton({ label: `Move ${value} down`, iconName: "arrow-down", size: "sm", onClick: () => move(index, 1), attrs: { disabled: index === values.length - 1, "data-action": "down" } }),
              iconButton({ label: `Remove ${value}`, iconName: "trash", size: "sm", onClick: () => remove(index), attrs: { "data-action": "remove" } }),
            ),
          ),
        ),
      );
      list.hidden = !values.length;
    }
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        add();
      }
    });
    render();
    return { el: h("div", null, list, h("div", { class: "list-add" }, input, addButton)), rerender: render };
  }

  // Build ---------------------------------------------------------------------------------
  function settingRow(field) {
    const ids = { label: uid("setting-label"), described: uid("setting-desc"), error: uid("setting-error") };
    const paths = fieldPaths(field);
    const control = buildControl(field, ids);
    let description = field.desc;
    if (field.kind === "dates") {
      description = [
        "Only messages in this range are scanned. The start date is stored in the base config (",
        pathText(form.meta.base_path),
        "), and a finished session moves it to its completion date.",
      ];
    }
    const error = h("p", { class: "setting-error", id: ids.error, role: "alert", hidden: true });
    const label = control.labelFor
      ? h("label", { class: "setting-label", id: ids.label, htmlFor: control.labelFor }, field.label)
      : h("span", { class: "setting-label", id: ids.label }, field.label);
    const element = h(
      "div",
      { class: "setting", "data-wide": field.wide },
      h("div", { class: "setting-info" }, label, description && h("p", { class: "setting-desc", id: ids.described }, description)),
      h("div", { class: "setting-control" }, control.el),
      error,
    );
    return { element, paths, error, control, describedBy: description ? ids.described : null, errorId: ids.error };
  }

  function build() {
    rows = [];
    indexMarks = [];
    observer?.disconnect();

    const groups = SECTIONS.map((section) => {
      const sectionRows = section.fields.map(settingRow);
      rows.push(...sectionRows.map((row) => ({ ...row, section: section.id })));
      const titleId = uid("settings-title");
      return h(
        "section",
        { class: "panel settings-group", id: `settings-${section.id}`, "aria-labelledby": titleId, tabindex: "-1" },
        h("div", { class: "group-head" }, h("h2", { class: "panel-title", id: titleId }, section.title), h("p", { class: "group-desc" }, section.desc)),
        sectionRows.map((row) => row.element),
      );
    });

    // Section spy: the section crossing a reading line 40% down the scroller is current, or
    // the last one once the end of the form is in view. A click pins its section until the
    // next scroll moves the line. IntersectionObserver only, no scroll listener.
    const visible = new Set();
    let pinned = null;
    let pinnedAt = 0;
    function markCurrent() {
      if (pinned && performance.now() - pinnedAt > PIN_SETTLE_MS) pinned = null;
      const reading = SECTIONS.find((section) => visible.has(`settings-${section.id}`))?.id ?? null;
      const current = pinned ?? (visible.has("settings-end") ? SECTIONS[SECTIONS.length - 1].id : reading);
      if (!current) return;
      for (const item of indexMarks) setAttr(item.link, "aria-current", item.id === current ? "true" : null);
    }

    const index = h(
      "nav",
      { class: "settings-index", "aria-label": "Settings sections" },
      SECTIONS.map((section) => {
        const mark = h("span", { class: "index-mark", hidden: true });
        const link = h(
          "button",
          {
            class: "index-link",
            type: "button",
            onClick: () => {
              // Scroll and move focus, so the next Tab lands inside the chosen section.
              pinned = section.id;
              pinnedAt = performance.now();
              markCurrent();
              const target = document.getElementById(`settings-${section.id}`);
              target?.scrollIntoView({ block: "start", behavior: "auto" });
              target?.focus({ preventScroll: true });
            },
          },
          h("span", null, section.title),
          mark,
        );
        indexMarks.push({ id: section.id, mark, link });
        return link;
      }),
    );

    const files = h(
      "section",
      { class: "panel", "aria-label": "Config files" },
      h(
        "div",
        { class: "panel-body paths" },
        h("p", { class: "path-row" }, h("span", { class: "micro" }, "Saved to"), pathText(form.meta.local_path), !form.meta.local_exists && h("span", { class: "panel-note" }, "created on the first save")),
        h("p", { class: "path-row" }, h("span", { class: "micro" }, "Base file"), pathText(form.meta.base_path), h("span", { class: "panel-note" }, "only the start date is written here")),
      ),
    );

    const end = h("div", { id: "settings-end", "aria-hidden": "true" });
    page.replaceChildren(index, h("form", { class: "settings-form", novalidate: true, onSubmit: (event) => event.preventDefault() }, notices, files, groups, end), savebar);
    namingPreview();
    sync();

    const track = (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target.id);
        else visible.delete(entry.target.id);
      }
      markCurrent();
    };
    observer = new IntersectionObserver(track, { root, rootMargin: "-40% 0px -59% 0px" });
    for (const group of groups) observer.observe(group);
    endObserver?.disconnect();
    endObserver = new IntersectionObserver(track, { root });
    endObserver.observe(end);
  }

  // Sync ------------------------------------------------------------------------------------
  function sync() {
    const dirty = new Set(dirtyPaths());
    const active = isActive(session.get().status);
    const counts = {};
    let errorFields = 0;

    for (const row of rows) {
      const messages = row.paths.flatMap((path) => form.errors[path] ?? []);
      const isDirty = row.paths.some((path) => dirty.has(path));
      setAttr(row.element, "data-dirty", isDirty);
      row.error.hidden = !messages.length;
      if (messages.length) row.error.replaceChildren(icon("warning-circle"), h("span", null, messages.join(" ")));
      // The visible message is also read with the field: description first, then the error.
      const describedBy = [row.describedBy, messages.length ? row.errorId : null].filter(Boolean).join(" ") || null;
      for (const input of row.control.inputs ?? []) {
        setAttr(input, "aria-invalid", messages.length ? "true" : null);
        setAttr(input, "aria-describedby", describedBy);
      }
      if (row.control.invalidTarget) {
        setAttr(row.control.invalidTarget, "data-invalid", messages.length ? "true" : null);
        setAttr(row.control.invalidTarget, "aria-describedby", describedBy);
      }
      const count = (counts[row.section] = counts[row.section] ?? { dirty: 0, errors: 0 });
      if (isDirty) count.dirty += 1;
      if (messages.length) {
        count.errors += 1;
        errorFields += 1;
      }
    }
    for (const item of indexMarks) {
      const count = counts[item.id] ?? { dirty: 0, errors: 0 };
      item.mark.hidden = !count.dirty && !count.errors;
      setAttr(item.mark, "data-tone", count.errors ? "err" : null);
      setText(item.mark, count.errors || count.dirty);
      setAttr(item.mark, "title", count.errors ? `${count.errors} to fix` : `${count.dirty} edited`);
    }

    const noticeNodes = [];
    if (active) {
      noticeNodes.push(callout({ tone: "warn", title: "A session is running", text: "You can keep editing. Saving is available once the session ends." }));
    }
    if (form.general.length) {
      noticeNodes.push(callout({ tone: "err", role: "alert", title: "The settings were not saved", list: form.general }));
    }
    const signature = `${active}|${form.general.join("|")}`;
    if (notices.dataset.signature !== signature) {
      notices.dataset.signature = signature;
      notices.replaceChildren(...noticeNodes);
    }

    setAttr(savebar, "data-open", dirty.size > 0);
    saveButton.disabled = active;
    setAttr(saveButton, "title", active ? "Saving is available once the session ends" : null);
    if (errorFields) {
      setAttr(saveStatus, "data-tone", "err");
      saveStatus.replaceChildren(icon("warning-circle"), `${errorFields} ${plural(errorFields, "field")} to fix`);
    } else {
      setAttr(saveStatus, "data-tone", null);
      saveStatus.replaceChildren(`${dirty.size} unsaved ${plural(dirty.size, "change")}`);
    }
  }

  function focusFirstError() {
    const row = rows.find((item) => item.paths.some((path) => form.errors[path]));
    if (!row) {
      root.scrollTop = 0;
      return;
    }
    row.element.scrollIntoView({ block: "center", behavior: "auto" });
    (row.control.inputs?.[0] ?? row.element.querySelector("input, button"))?.focus({ preventScroll: true });
  }

  function reset() {
    const position = root.scrollTop;
    form.values = clone(form.initial);
    form.errors = {};
    form.rowErrors = {};
    form.general = [];
    build();
    root.scrollTop = position;
  }

  async function save() {
    const dirty = dirtyPaths();
    if (!dirty.length || isActive(session.get().status)) return;
    const checked = validate(dirty);
    form.errors = checked.errors;
    form.rowErrors = checked.rowErrors;
    form.general = [];
    if (Object.keys(checked.errors).length) {
      rows.find((row) => row.paths.includes("channels"))?.control.rerender?.();
      sync();
      focusFirstError();
      return;
    }
    await withBusy(saveButton, async () => {
      try {
        const data = await api.saveConfig(buildPayload(dirty));
        if (disposed) {
          adopt(data);
          return;
        }
        const position = root.scrollTop;
        adopt(data);
        build();
        root.scrollTop = position;
        // Name the files that actually changed: the start date lives in the base config.
        const files = [];
        if (dirty.some((path) => !BASE_FILE_PATHS.has(path))) files.push(form.meta.local_path);
        if (dirty.some((path) => BASE_FILE_PATHS.has(path))) files.push(form.meta.base_path);
        toast({ tone: "ok", title: "Settings saved", message: ["Written to ", files.flatMap((file, index) => [index ? " and " : "", pathText(file)])] });
      } catch (error) {
        if (error.status === 400 && error.details.length) applyServerDetails(error.details);
        else if (error.status === 409) form.general = ["A download session is running. Settings can be saved once it ends."];
        else form.general = [error.message];
        if (disposed) return;
        rows.find((row) => row.paths.includes("channels"))?.control.rerender?.();
        sync();
        focusFirstError();
      }
    });
  }

  function onKey(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      save();
    }
  }

  async function load() {
    page.replaceChildren(
      h("div", { class: "skeleton-wrap", "aria-hidden": "true" }, skeleton("100%", "14rem")),
      h("div", { class: "skeleton-wrap settings-form", "aria-hidden": "true" }, skeleton("100%", "5rem"), skeleton("100%", "16rem"), skeleton("100%", "20rem")),
    );
    try {
      adopt(await api.config());
      if (!disposed) build();
    } catch (error) {
      if (disposed) return;
      page.replaceChildren(
        h(
          "div",
          { class: "settings-form" },
          callout({
            tone: "err",
            role: "alert",
            title: "The settings could not be loaded",
            text: error.message,
            actions: button({ label: "Try again", iconName: "arrow-clockwise", size: "sm", onClick: load }),
          }),
        ),
      );
    }
  }

  document.addEventListener("keydown", onKey);
  const unsubscribe = session.subscribe(() => {
    if (form.loaded && rows.length) sync();
  });
  if (form.loaded) build();
  else load();

  return () => {
    disposed = true;
    observer?.disconnect();
    endObserver?.disconnect();
    unsubscribe();
    document.removeEventListener("keydown", onKey);
  };
}
