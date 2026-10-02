// Kit: the primitive showcase (DESIGN.md section 5). Reachable at #/kit, not linked in the nav.

import { h, icon } from "../dom.js";
import {
  button,
  callout,
  confirmDialog,
  empty,
  eqGlyph,
  iconButton,
  keycap,
  linkButton,
  segmented,
  SESSION_STATES,
  skeleton,
  stateBadge,
  switchControl,
  toast,
  transport,
  withBusy,
} from "../ui.js";

function cell(title, ...children) {
  return h("section", { class: "panel kit-cell" }, h("h2", { class: "panel-title" }, title), children);
}

const row = (...children) => h("div", { class: "kit-row" }, children);

function meter(mode, fraction, live) {
  const bars = () => Array.from({ length: 48 }, (_, index) => h("i", { style: { "--h": (0.25 + 0.7 * Math.abs(Math.sin(index * 0.7))).toFixed(2) } }));
  return h(
    "div",
    { class: "meter", role: "progressbar", "aria-label": `Meter, ${mode}`, "aria-valuemin": "0", "aria-valuemax": "100", "data-mode": mode, "data-live": live, style: { "--p": String(fraction) } },
    h("div", { class: "meter-bars" }, bars()),
    h("div", { class: "meter-clip" }, h("div", { class: "meter-clip-inner" }, h("div", { class: "meter-bars meter-fill" }, bars()))),
    h("div", { class: "meter-head" }),
  );
}

export function mount(root) {
  const busy = button({ label: "Run for 2 seconds", iconName: "floppy-disk", variant: "primary" });
  busy.addEventListener("click", () => withBusy(busy, () => new Promise((resolve) => setTimeout(resolve, 2000))));

  const invalid = h("input", { class: "input", id: "kit-invalid", value: "40", "aria-invalid": "true", "aria-describedby": "kit-invalid-error" });

  root.append(
    h(
      "div",
      { class: "page" },
      h("p", { class: "page-lead" }, "Every primitive of the Signal design system with its states. Used for visual QA."),
      h(
        "div",
        { class: "kit-grid" },
        cell(
          "Buttons",
          row(button({ label: "Primary", variant: "primary" }), button({ label: "Secondary" }), button({ label: "Ghost", variant: "ghost" }), button({ label: "Danger", variant: "danger" })),
          row(button({ label: "Small", size: "sm" }), button({ label: "Medium" }), button({ label: "Large", size: "lg" }), button({ label: "Disabled", attrs: { disabled: true } })),
          row(busy, linkButton({ label: "Link button", href: "#/kit", iconName: "arrow-right" }), iconButton({ label: "Icon button", iconName: "arrow-clockwise", outlined: true }), iconButton({ label: "Pressed icon button", iconName: "pause", outlined: true, attrs: { "aria-pressed": "true" } })),
        ),
        cell("Transport", row(transport({ kind: "start", label: "Start session" }), transport({ kind: "stop", label: "Stop session" })), row(transport({ kind: "stop", label: "Stop", size: "sm" }))),
        cell(
          "Fields",
          h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "kit-text" }, "Label above"), h("input", { class: "input", id: "kit-text", placeholder: "Placeholder text" }), h("p", { class: "field-help" }, "Help text sits below the control.")),
          h(
            "div",
            { class: "field" },
            h("label", { class: "field-label", htmlFor: "kit-invalid" }, "Invalid"),
            h("div", { class: "input-wrap", "data-suffix": true }, invalid, h("span", { class: "input-suffix micro" }, "files")),
            h("p", { class: "field-error", id: "kit-invalid-error" }, icon("warning-circle"), "Use a whole number from 1 to 20."),
          ),
          h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "kit-disabled" }, "Disabled"), h("input", { class: "input", id: "kit-disabled", value: "Read only", disabled: true })),
        ),
        cell(
          "Selection",
          row(switchControl({ id: "kit-switch-on", checked: true, onChange: () => {} }).el, h("label", { htmlFor: "kit-switch-on" }, "Switch on"), switchControl({ id: "kit-switch-off", checked: false, onChange: () => {} }).el, h("label", { htmlFor: "kit-switch-off" }, "Switch off")),
          row(
            h("label", { class: "check" }, h("input", { type: "checkbox", checked: true }), h("span", { class: "check-box" }, icon("check-bold")), h("span", null, "Audio")),
            h("label", { class: "check" }, h("input", { type: "checkbox" }), h("span", { class: "check-box" }, icon("check-bold")), h("span", null, "Document")),
          ),
          row(segmented({ label: "Log level", options: ["DEBUG", "INFO", "WARNING", "ERROR"].map((value) => ({ value, label: value })), value: "INFO", onChange: () => {} }).el),
          row(
            h("button", { class: "chip-toggle", type: "button", "aria-pressed": "true" }, "Info", h("span", { class: "chip-count" }, "677")),
            h("button", { class: "chip-toggle", type: "button", "aria-pressed": "true", "data-tone": "err" }, "Error", h("span", { class: "chip-count" }, "9")),
            h("button", { class: "chip-toggle", type: "button", "aria-pressed": "false" }, "Debug", h("span", { class: "chip-count" }, "15")),
          ),
        ),
        cell(
          "State badges",
          row(Object.keys(SESSION_STATES).map((state) => stateBadge(state).el)),
          row(keycap("W1"), keycap("Ctrl S"), keycap("/"), eqGlyph(true), eqGlyph(false)),
          row(
            h("span", { class: "chip", "data-tone": "ok" }, h("span", { class: "chip-glyph" }, icon("user-circle-fill")), "Mira"),
            h("span", { class: "chip", "data-tone": "warn" }, h("span", { class: "chip-glyph" }, icon("sign-in")), "Signed out"),
            h("span", { class: "chip", "data-tone": "err" }, h("span", { class: "chip-glyph" }, icon("wifi-slash")), "Server offline"),
          ),
        ),
        cell("Meter", meter("determinate", 0.42, true), meter("indeterminate", 0, false), meter("rest", 0, false)),
        cell(
          "Callouts",
          callout({ tone: "info", title: "Information", text: "Neutral context for the operator." }),
          callout({ tone: "ok", title: "Success", text: "The changed state is the confirmation." }),
          callout({ tone: "warn", title: "Warning", text: "Something needs attention before it fails." }),
          callout({ tone: "err", title: "Error", text: "What failed, with the cause next to it.", list: ["download.concurrent_downloads must be an integer between 1 and 20"] }),
        ),
        cell(
          "Overlays",
          row(
            button({ label: "Toast: success", onClick: () => toast({ tone: "ok", title: "Settings saved", message: "Written to src\\local_config.yaml" }) }),
            button({ label: "Toast: error", onClick: () => toast({ tone: "err", title: "Library refresh failed", message: "Cannot reach the local server." }) }),
          ),
          row(
            button({
              label: "Confirm dialog",
              variant: "danger",
              onClick: () => confirmDialog({ title: "Stop this session?", body: "Downloads in progress are cancelled and start from zero next time.", confirmLabel: "Stop session", cancelLabel: "Keep running" }),
            }),
          ),
        ),
        cell("Loading and empty", skeleton("60%", "1rem"), skeleton("100%", "3rem"), empty({ iconName: "file-audio", title: "No files yet", text: "The newest downloads are listed here." })),
      ),
    ),
  );
  return null;
}
