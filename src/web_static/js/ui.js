// Primitive builders (DESIGN.md section 5), toasts and dialogs.

import { h, icon } from "./dom.js";

let sequence = 0;
export const uid = (prefix = "id") => `${prefix}-${++sequence}`;

export const SESSION_STATES = {
  idle: { label: "Idle", tone: "muted", glyph: "circle" },
  connecting: { label: "Connecting", tone: "info", glyph: "circle-notch", spin: true },
  running: { label: "Running", tone: "ok", eq: true },
  stopping: { label: "Stopping", tone: "warn", glyph: "hourglass-medium" },
  finished: { label: "Finished", tone: "ok", glyph: "check-circle-fill" },
  stopped: { label: "Stopped", tone: "skip", glyph: "stop-fill" },
  failed: { label: "Failed", tone: "err", glyph: "warning-fill" },
};

export function sessionMeta(state) {
  return SESSION_STATES[state] ?? { label: String(state ?? "Unknown"), tone: "muted", glyph: "question" };
}

export function eqGlyph(live = false) {
  return h("span", { class: "eq", "data-live": live, "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i"));
}

/** State badge that only touches the DOM when the state changes. */
export function stateBadge(initial) {
  const el = h("span", { class: "state-badge" });
  let current;
  const set = (state) => {
    if (state === current) return;
    current = state;
    const meta = sessionMeta(state);
    el.dataset.tone = meta.tone;
    el.replaceChildren(
      meta.eq ? eqGlyph(true) : icon(meta.glyph, { cls: meta.spin ? "spin" : undefined }),
      document.createTextNode(meta.label),
    );
  };
  set(initial);
  return { el, set };
}

export function button({ label, iconName, variant, size, type = "button", onClick, attrs }) {
  return h(
    "button",
    { class: "btn", type, "data-variant": variant, "data-size": size, onClick, ...attrs },
    iconName && icon(iconName, { cls: "btn-icon" }),
    iconName && icon("circle-notch", { cls: "spinner" }),
    h("span", { class: "btn-label" }, label),
  );
}

export function linkButton({ label, href, iconName, variant, size }) {
  return h(
    "a",
    { class: "btn", href, "data-variant": variant, "data-size": size },
    iconName && icon(iconName, { cls: "btn-icon" }),
    h("span", { class: "btn-label" }, label),
  );
}

export function iconButton({ label, iconName, size, outlined, onClick, attrs }) {
  return h(
    "button",
    { class: "icon-btn", type: "button", "aria-label": label, title: label, "data-size": size, "data-outlined": outlined, onClick, ...attrs },
    icon(iconName),
  );
}

export function transport({ kind, label, size, type = "button", onClick }) {
  return h(
    "button",
    { class: "transport", type, "data-kind": kind, "data-size": size, onClick },
    h(
      "span",
      { class: "transport-well" },
      icon(kind === "stop" ? "stop-fill" : "play-fill", { cls: "btn-icon" }),
      icon("circle-notch", { cls: "spinner" }),
    ),
    h("span", { class: "transport-label" }, label),
  );
}

/** Runs an async task once per control: a second activation while busy is ignored. */
export async function withBusy(control, task) {
  if (control.getAttribute("aria-busy") === "true") return undefined;
  control.setAttribute("aria-busy", "true");
  try {
    return await task();
  } finally {
    control.removeAttribute("aria-busy");
  }
}

export function keycap(text) {
  return h("kbd", { class: "keycap" }, text);
}

const CALLOUT_ICONS = { ok: "check-circle", info: "info", warn: "warning", err: "warning-circle", muted: "info", skip: "info" };

export function callout({ tone = "info", title, text, list, actions, iconName, role }) {
  const paragraphs = Array.isArray(text) ? text : text ? [text] : [];
  return h(
    "div",
    { class: "callout", "data-tone": tone, role },
    icon(iconName ?? CALLOUT_ICONS[tone] ?? "info"),
    h(
      "div",
      { class: "callout-body" },
      title && h("p", { class: "callout-title" }, title),
      paragraphs.map((paragraph) => h("p", null, paragraph)),
      list?.length ? h("ul", null, list.map((item) => h("li", null, item))) : null,
    ),
    actions && h("div", { class: "callout-actions" }, actions),
  );
}

export function empty({ iconName, title, text, action }) {
  return h(
    "div",
    { class: "empty" },
    h("div", { class: "empty-icon" }, icon(iconName)),
    h("p", { class: "empty-title" }, title),
    text && h("p", { class: "empty-text" }, text),
    action,
  );
}

export function skeleton(width, height) {
  const style = {};
  if (width) style["--w"] = width;
  if (height) style["--h"] = height;
  return h("span", { class: "skeleton", style, "aria-hidden": "true" });
}

export function panel({ title, note, actions, body, cls, id }) {
  const titleId = title ? uid("panel-title") : null;
  return h(
    "section",
    { class: cls ? `panel ${cls}` : "panel", id, "aria-labelledby": titleId },
    title &&
      h(
        "header",
        { class: "panel-head" },
        h("div", null, h("h2", { class: "panel-title", id: titleId }, title), note && h("p", { class: "panel-note" }, note)),
        actions && h("div", { class: "panel-actions" }, actions),
      ),
    h("div", { class: "panel-body" }, body),
  );
}

export function switchControl({ id, checked, onChange }) {
  const el = h(
    "button",
    { class: "switch", type: "button", role: "switch", id, "aria-checked": String(Boolean(checked)) },
    h("span", { class: "switch-thumb" }),
  );
  el.addEventListener("click", () => {
    const next = el.getAttribute("aria-checked") !== "true";
    el.setAttribute("aria-checked", String(next));
    onChange(next);
  });
  return { el, set: (value) => el.setAttribute("aria-checked", String(Boolean(value))) };
}

/** Radio group with roving tabindex and arrow-key selection. */
export function segmented({ label, labelledBy, options, value, onChange }) {
  let current = String(value);
  const buttons = options.map((option) =>
    h("button", { class: "segment", type: "button", role: "radio", "data-value": option.value }, option.label),
  );
  const el = h("div", { class: "segmented", role: "radiogroup", "aria-label": label, "aria-labelledby": labelledBy }, buttons);
  const sync = () => {
    const known = buttons.some((item) => item.dataset.value === current);
    buttons.forEach((item, index) => {
      const selected = item.dataset.value === current;
      item.setAttribute("aria-checked", String(selected));
      item.tabIndex = selected || (!known && index === 0) ? 0 : -1;
    });
  };
  const select = (next, focus) => {
    if (next !== current) {
      current = next;
      sync();
      onChange(next);
    }
    if (focus) buttons.find((item) => item.dataset.value === next)?.focus();
  };
  el.addEventListener("click", (event) => {
    const item = event.target.closest(".segment");
    if (item) select(item.dataset.value, false);
  });
  el.addEventListener("keydown", (event) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = Math.max(0, buttons.findIndex((item) => item.dataset.value === current));
    select(buttons[(index + step + buttons.length) % buttons.length].dataset.value, true);
  });
  sync();
  return {
    el,
    set(next) {
      current = String(next);
      sync();
    },
  };
}

export function announce(message) {
  const region = document.getElementById("announcer");
  if (region) region.textContent = message;
}

// Toasts ----------------------------------------------------------------------

const TOAST_ICONS = { ok: "check-circle-fill", err: "warning-circle-fill", warn: "warning-fill", info: "info-fill" };
const TOAST_LIMIT = 4;

export function toast({ tone = "info", title, message, duration }) {
  const host = document.getElementById("toasts");
  let remaining = duration ?? (tone === "err" ? 8000 : 4200);
  let timer = null;
  let startedAt = 0;

  const dismiss = () => {
    clearTimeout(timer);
    if (!el.isConnected || el.hasAttribute("data-leaving")) return;
    el.setAttribute("data-leaving", "");
    el.addEventListener("animationend", () => el.remove(), { once: true });
    setTimeout(() => el.remove(), 400);
  };
  const resume = () => {
    clearTimeout(timer);
    startedAt = Date.now();
    timer = setTimeout(dismiss, remaining);
  };
  const pause = () => {
    clearTimeout(timer);
    remaining = Math.max(1200, remaining - (Date.now() - startedAt));
  };

  const el = h(
    "div",
    { class: "toast", "data-tone": tone, role: tone === "err" ? "alert" : "status" },
    icon(TOAST_ICONS[tone] ?? TOAST_ICONS.info),
    h("div", { class: "toast-body" }, h("p", { class: "toast-title" }, title), message && h("p", { class: "toast-msg" }, message)),
    iconButton({ label: "Dismiss notification", iconName: "x", size: "sm", onClick: dismiss }),
  );
  el.addEventListener("pointerenter", pause);
  el.addEventListener("pointerleave", resume);
  el.addEventListener("focusin", pause);
  el.addEventListener("focusout", resume);

  host.append(el);
  while (host.children.length > TOAST_LIMIT) host.firstElementChild.remove();
  resume();
  return dismiss;
}

// Dialog ------------------------------------------------------------------------

/**
 * Confirmation dialog. Resolves true only when the confirm button is used. Initial focus
 * lands on the safe (cancel) button, so Enter never triggers the destructive outcome.
 */
export function confirmDialog({ title, body, confirmLabel, cancelLabel = "Cancel", tone = "err", iconName = "warning", confirmVariant = "danger" }) {
  return new Promise((resolve) => {
    const opener = document.activeElement;
    const titleId = uid("dialog-title");
    let result = false;
    let closing = false;

    const close = (value) => {
      if (closing) return;
      closing = true;
      result = value;
      dialog.setAttribute("data-closing", "");
      const finish = () => {
        if (dialog.open) dialog.close();
      };
      panelElement.addEventListener("animationend", finish, { once: true });
      setTimeout(finish, 240);
    };

    const paragraphs = Array.isArray(body) ? body : [body];
    const cancelButton = button({ label: cancelLabel, variant: "secondary", onClick: () => close(false) });
    const panelElement = h(
      "div",
      { class: "dialog-panel", tabindex: "-1" },
      h("div", { class: "dialog-icon", "data-tone": tone }, icon(iconName)),
      h("h2", { class: "dialog-title", id: titleId }, title),
      h("div", { class: "dialog-body" }, paragraphs.map((paragraph) => (paragraph instanceof Node ? paragraph : h("p", null, paragraph)))),
      h(
        "div",
        { class: "dialog-actions" },
        cancelButton,
        button({ label: confirmLabel, variant: confirmVariant, onClick: () => close(true) }),
      ),
    );
    const dialog = h("dialog", { class: "dialog", "aria-labelledby": titleId }, panelElement);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close(false);
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) close(false);
    });
    dialog.addEventListener("close", () => {
      dialog.remove();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
      resolve(result);
    });

    document.body.append(dialog);
    dialog.showModal();
    cancelButton.focus();
  });
}
