// Library: registry totals, per-channel table, download setup, recent files, registry cleanup.

import { api } from "../api.js";
import { fileName, h, icon, pathText, setText } from "../dom.js";
import { fmtDateTime, fmtDay, fmtInt, fmtRelative, fmtSize, fmtSizeText, MISSING, plural } from "../format.js";
import { isActive, session } from "../store.js";
import { button, callout, confirmDialog, empty, linkButton, panel, skeleton, toast, withBusy } from "../ui.js";

const RECENT_PREVIEW = 12;

function rangeText(min, max, unit) {
  const hasMin = min !== null && min !== undefined;
  const hasMax = max !== null && max !== undefined;
  if (hasMin && hasMax) return `${min} to ${max} ${unit}`;
  if (hasMin) return `At least ${min} ${unit}`;
  if (hasMax) return `Up to ${max} ${unit}`;
  return "No limit";
}

function dateRangeText(from, to) {
  if (from && to) return `${fmtDay(from)} to ${fmtDay(to)}`;
  if (from) return `From ${fmtDay(from)}`;
  if (to) return `Until ${fmtDay(to)}`;
  return "No limit";
}

function readout(label, iconName, value, unit) {
  return h(
    "div",
    { class: "readout" },
    h("dt", null, icon(iconName), h("span", null, label)),
    h("dd", null, h("span", { class: "readout-value" }, value), unit && h("span", { class: "readout-unit" }, unit)),
  );
}

export function mount(root) {
  let stats = null;
  let loading = false;
  let disposed = false;
  let expanded = false;

  const refreshButton = button({ label: "Refresh", iconName: "arrow-clockwise", variant: "ghost", size: "sm", onClick: () => load() });
  const content = h("div", { class: "page library" });
  root.append(content);

  // Maintenance block is built once so its result survives refreshes.
  const cleanupResult = h("div", { class: "maintenance-result" });
  const cleanupNote = h("p", { class: "field-help" });
  const cleanupButton = button({ label: "Clean up registry", iconName: "broom", variant: "secondary", onClick: onCleanup });
  const maintenance = h(
    "section",
    { class: "panel maintenance", "aria-labelledby": "maintenance-title" },
    h("div", { class: "empty-icon" }, icon("broom")),
    h(
      "div",
      { class: "maintenance-text" },
      h("h2", { class: "panel-title", id: "maintenance-title" }, "Clean up missing entries"),
      h(
        "p",
        { class: "panel-note" },
        "Removes registry entries whose files are no longer on disk. It never deletes media, clears the blacklist, resets scan checkpoints or schedules re-downloads.",
      ),
      cleanupNote,
    ),
    cleanupButton,
    cleanupResult,
  );

  function renderCleanupAvailability() {
    const active = isActive(session.get().status);
    cleanupButton.disabled = active;
    setText(cleanupNote, active ? "Available once the running session ends." : "");
    cleanupNote.hidden = !active;
  }

  async function onCleanup() {
    const confirmed = await confirmDialog({
      title: "Remove missing entries?",
      body: [
        "Entries whose files are no longer on disk are removed from the download registry.",
        "No media is deleted. The blacklist and the scan checkpoints stay exactly as they are.",
      ],
      confirmLabel: "Clean up registry",
      cancelLabel: "Keep registry",
      tone: "warn",
      iconName: "broom",
      confirmVariant: "primary",
    });
    if (!confirmed) return;
    await withBusy(cleanupButton, async () => {
      try {
        const result = await api.cleanup();
        const removed = Number(result?.removed ?? 0);
        cleanupResult.replaceChildren(
          removed > 0
            ? callout({ tone: "ok", role: "status", title: `Removed ${fmtInt(removed)} registry ${plural(removed, "entry", "entries")}`, text: "The files were already gone from disk. Media and checkpoints were not touched." })
            : callout({ tone: "info", role: "status", title: "Nothing to remove", text: "Every registered file is still on disk." }),
        );
        load({ quiet: true });
      } catch (error) {
        cleanupResult.replaceChildren(
          error.status === 409
            ? callout({ tone: "warn", role: "alert", title: "A session is running", text: "Clean up is available once it ends." })
            : callout({ tone: "err", role: "alert", title: "Clean up failed", text: error.message, list: error.details }),
        );
      }
    });
  }

  function head() {
    return h(
      "div",
      { class: "page-head" },
      h("p", { class: "page-lead" }, "Everything registered as downloaded, grouped by channel folder."),
      refreshButton,
    );
  }

  function renderLoading() {
    content.replaceChildren(
      head(),
      h("div", { class: "skeleton-wrap page", "aria-hidden": "true" }, skeleton("100%", "6rem"), skeleton("100%", "14rem"), skeleton("100%", "18rem")),
    );
  }

  function channelsPanel(data) {
    const channels = data.channels ?? [];
    const totalSize = data.totals?.total_size_mb || 0;
    // The API rounds sizes to 0.1 MB; while the total rounds to zero, share by file count.
    const totalFiles = data.totals?.downloaded || 0;
    if (!channels.length) {
      return panel({
        title: "Channels",
        body: empty({
          iconName: "vinyl-record",
          title: "No downloads registered yet",
          text: "Channel folders appear here after the first session downloads a file.",
          action: linkButton({ label: "Open dashboard", href: "#/dashboard", iconName: "arrow-right", size: "sm" }),
        }),
      });
    }
    const rows = channels.map((channel) => {
      const share = totalSize > 0 ? channel.total_size_mb / totalSize : totalFiles > 0 ? channel.downloaded / totalFiles : 0;
      return h(
        "tr",
        null,
        h("td", { "data-span": true }, h("div", { class: "cell-main" }, h("span", { class: "cell-title mono" }, channel.channel_id), h("span", { class: "cell-sub mono", title: channel.folder }, channel.folder))),
        h("td", { class: "col-num", "data-label": "Files" }, fmtInt(channel.downloaded)),
        h("td", { class: "col-num", "data-label": "Size" }, fmtSizeText(channel.total_size_mb, { nonEmpty: channel.downloaded > 0 })),
        h(
          "td",
          { "data-label": "Share" },
          h("div", { class: "share" }, h("span", { class: "share-bar", style: { "--share": share.toFixed(4) }, "aria-hidden": "true" }), h("span", { class: "mono num" }, `${Math.round(share * 100)}%`)),
        ),
        h("td", { class: "col-num", "data-label": "Blacklisted" }, fmtInt(channel.blacklisted)),
        h("td", { class: "col-num mono", "data-label": "Checkpoint" }, channel.last_safe_message_id ?? MISSING),
      );
    });
    return panel({
      title: "Channels",
      note: "Checkpoint is the last message id that is safe to resume after.",
      body: h(
        "table",
        { class: "table" },
        h("thead", null, h("tr", null, h("th", { scope: "col" }, "Channel"), h("th", { scope: "col", class: "col-num" }, "Files"), h("th", { scope: "col", class: "col-num" }, "Size"), h("th", { scope: "col" }, "Share"), h("th", { scope: "col", class: "col-num" }, "Blacklisted"), h("th", { scope: "col", class: "col-num" }, "Checkpoint"))),
        h("tbody", null, rows),
      ),
    });
  }

  function setupPanel(data) {
    const filters = data.filters ?? {};
    const formats = filters.allowed_formats ?? [];
    const types = (filters.file_types ?? []).map((type) => type.charAt(0).toUpperCase() + type.slice(1));
    const size = filters.size_range_mb ?? {};
    const dates = filters.date_range ?? {};
    const row = (label, value) => [h("dt", null, label), h("dd", null, value)];
    return panel({
      title: "Download setup",
      actions: linkButton({ label: "Edit", href: "#/settings", iconName: "sliders-horizontal", variant: "ghost", size: "sm" }),
      body: h(
        "dl",
        { class: "kv" },
        row("Output folder", pathText(data.output_dir ?? MISSING)),
        row("File name", h("span", { class: "mono" }, data.naming_template ?? MISSING)),
        row("Workers", h("span", { class: "num" }, `${fmtInt(data.workers)}, queue of ${fmtInt(data.queue_size)}`)),
        row("Rate limit", h("span", { class: "num" }, `${data.requests_per_second ?? MISSING} requests per second`)),
        row("File types", types.length ? types.join(", ") : MISSING),
        row("Formats", formats.length ? h("div", { class: "format-list" }, formats.map((format) => h("span", { class: "token mono" }, format))) : MISSING),
        row("Size", rangeText(size.min, size.max, "MB")),
        row("Message date", dateRangeText(dates.from, dates.to)),
      ),
    });
  }

  function recentPanel(data) {
    const recent = data.recent ?? [];
    if (!recent.length) {
      return panel({
        title: "Recent downloads",
        body: empty({ iconName: "file-audio", title: "No files yet", text: "The newest downloads are listed here, up to 50." }),
      });
    }
    const visible = expanded ? recent : recent.slice(0, RECENT_PREVIEW);
    const rows = visible.map((item) =>
      h(
        "li",
        { class: "recent-row" },
        fileName(item.filename),
        h("span", { class: "recent-chan mono" }, item.channel_id),
        h("span", { class: "recent-size mono num" }, fmtSizeText(item.file_size_mb, { nonEmpty: true })),
        h("span", { class: "recent-date num", title: fmtDateTime(item.download_date) }, fmtRelative(item.download_date)),
      ),
    );
    const more =
      recent.length > RECENT_PREVIEW &&
      h(
        "div",
        { class: "recent-more" },
        button({
          label: expanded ? "Show fewer" : `Show all ${recent.length}`,
          iconName: expanded ? "caret-up" : "caret-down",
          variant: "ghost",
          size: "sm",
          onClick: () => {
            expanded = !expanded;
            render();
          },
        }),
      );
    return panel({
      title: "Recent downloads",
      note: `Newest first, ${recent.length} listed`,
      body: [
        h("div", { class: "recent-row recent-head micro", "aria-hidden": "true" }, h("span", null, "File"), h("span", null, "Channel"), h("span", { class: "recent-size" }, "Size"), h("span", { class: "recent-date" }, "Downloaded")),
        h("ul", { class: "recent" }, rows),
        more,
      ],
    });
  }

  function render() {
    if (!stats) return;
    const totals = stats.totals ?? {};
    const size = fmtSize(totals.total_size_mb, { nonEmpty: totals.downloaded > 0 });
    // The channel table runs full width; the recent list and the setup card share a row.
    content.replaceChildren(
      head(),
      h(
        "dl",
        { class: "readouts", "aria-label": "Library totals" },
        readout("Files", "file-audio", fmtInt(totals.downloaded)),
        readout("On disk", "hard-drives", size.value, size.unit),
        readout("Channels", "broadcast", fmtInt(totals.channels)),
        readout("Blacklisted", "prohibit", fmtInt(totals.blacklisted)),
      ),
      channelsPanel(stats),
      h("div", { class: "library-cols" }, recentPanel(stats), setupPanel(stats)),
      maintenance,
    );
    renderCleanupAvailability();
  }

  async function load({ quiet = false } = {}) {
    if (loading) return;
    loading = true;
    if (!stats && !quiet) renderLoading();
    try {
      await withBusy(refreshButton, async () => {
        stats = await api.stats();
      });
      if (!disposed) render();
    } catch (error) {
      if (disposed) return;
      if (stats) {
        toast({ tone: "err", title: "Library refresh failed", message: error.message });
      } else {
        content.replaceChildren(
          head(),
          callout({
            tone: "err",
            role: "alert",
            title: "The library could not be loaded",
            text: error.message,
            actions: button({ label: "Try again", iconName: "arrow-clockwise", size: "sm", onClick: () => load() }),
          }),
        );
      }
    } finally {
      loading = false;
    }
  }

  let wasActive = isActive(session.get().status);
  const unsubscribe = session.subscribe(({ status }) => {
    const active = isActive(status);
    if (wasActive && !active) load({ quiet: true });
    wasActive = active;
    renderCleanupAvailability();
  });

  load();
  return () => {
    disposed = true;
    unsubscribe();
  };
}
