# Music Downloader Web UI - Design System ("Signal")

Contract for everything under `src/web_static/`. Raw color values live only in
`css/tokens.css`; every other stylesheet and script references tokens from this file.

## 0. Research Log

- Embedded refs: shortlisted `raycast`, `spotify`, `elevenlabs` -> picked Layer A `soft-skill`
  + Layer B `raycast`. This install materializes only `aside.md` (bright marketing, no fit), so
  both picks were fetched from their upstreams (Leonxlnx/taste-skill `skills/soft-skill`,
  VoltAgent/awesome-design-md `design-md/raycast`) and read in full. Raycast because its
  near-black surface ladder, hairline edges and keycaps are the closest material to audio
  hardware; Spotify was rejected as the token source because its green would make this read
  as a clone. The `design-taste-frontend` anti-slop rules supplied with the task also apply.
- Lazyweb: 4 queries, 6 screens viewed (Spotify, Epidemic Sound, Deezer, Linear settings,
  Render logs, Better Stack live tail) -> grammar taken: island panels on a black canvas plus
  a persistent transport bar (Spotify); the waveform as scrubber (Epidemic Sound); wide bold
  display type on near-black (Deezer); settings as grouped rows, label and description left,
  control right, section list beside a narrow column (Linear); log rows as time / level /
  message with a search-first toolbar (Render, Better Stack).
- StyleGallery: adopted `fixed-sidenav-shell` + `scroll-body-shell`. Scroll owner is `.view`;
  the Logs view nests one more owner, `.log-pane`, whose job is the log tail.
- beui.dev: read `theme-toggle`, `animated-toast-stack`, `switch`, `loader` sources ->
  View Transition circular reveal, toast spring 420/34/0.75 with 4200 ms dwell, heavy thumb
  spring 800/80/4, reduced-motion opacity pulse of 1.4 s.
- react-bits: read `Noise` (canvas grain redrawn every 2 frames, no reduced-motion path) ->
  retrofit to one static frame on a fixed, `pointer-events: none` layer. The waveform meter
  and the EQ glyph are novel mechanisms, recorded in Section 6.
- Imagen drafts: skipped - `generate_image` returned `missing_config` (no provider key).
  Three directions were written as full prompts and compared in text: Signal (graphite +
  phosphor lime, waveform progress), Tape machine (warm analog, amber VU), Cold glass (cobalt,
  frosted panels). Picked Signal: it is the boldest, its signature carries meaning, and amber
  and cobalt collide with the warning and info semantics this product needs.
- Skipped lanes: `ui-ux-db` and `open-design` (not shipped in this install); React dev tooling
  gate (not a React project); Lighthouse (no Playwright/Lighthouse without npm, see Section 8).

## 1. Atmosphere & Identity

A mastering console at night. Graphite hardware modules float on a near-black desk, every
number is set like an instrument readout, and a single phosphor-lime signal lights up whatever
is live. Idle, the room is dark and still; when a session runs, a low lime glow rises behind
the deck and the meter starts to move.

Signature: **the waveform is the progress bar.** Overall progress is a 96-bar audio waveform
that fills with lime from the left, and the bars at the play head dance like an equalizer
while files are downloading. Second idea: human copy is set in a wide grotesque, machine data
(file names, ids, paths, sizes, log lines) is always monospace.

Operator persona: one collector on a desktop, running long unattended sessions and glancing
at the screen from across the room. Hence one giant numeral, state that reads without color
alone, and a UI that stays light on CPU for hours.

## 2. Color

Dark is the default theme; light is a full peer (`data-theme` on `<html>`, persisted under
`tmd-theme`). Neutrals carry a faint olive tint (hue 125-135) so they sit with the accent.
Values are OKLCH; hex is the sRGB equivalent for reference.

### Palette

| Role | Token | Dark | Light | Usage |
|---|---|---|---|---|
| Canvas | `--canvas` | `0.130 0.006 135` #060806 | `0.965 0.005 125` #f3f4f0 | Page background |
| Surface 1 | `--surface-1` | `0.172 0.007 135` #0f110d | `0.995 0.002 125` #fdfefc | Panels, sidebar |
| Surface 2 | `--surface-2` | `0.205 0.008 135` #161814 | `0.975 0.004 125` #f6f7f4 | Inputs, inner cores, rows |
| Surface 3 | `--surface-3` | `0.245 0.009 135` #1f211d | `0.945 0.006 125` #ecede9 | Keycaps, pressed, thumbs |
| Surface 4 | `--surface-4` | `0.290 0.010 135` #292c28 | `0.995 0.002 125` | Toasts, dialogs |
| Inset | `--surface-inset` | `0.105 0.005 135` | `0.955 0.005 125` | Log pane, meter well |
| Line | `--line` | white 8% | black 9% | Hairline borders |
| Line strong | `--line-strong` | white 14% | black 16% | Control edges, dividers |
| Bezel | `--bezel` | white 7% | white 90% | 1px inner top highlight |
| Wash 1 / 2 / 3 | `--wash-1..3` | white 4 / 7 / 10% | black 4 / 6 / 9% | Hover, selected, pressed |
| Text 1 | `--text-1` | `0.965 0.006 125` #f2f4f0 | `0.200 0.012 135` #141712 | Headings, values |
| Text 2 | `--text-2` | `0.800 0.012 130` #bbbfb7 | `0.380 0.012 135` #40443e | Body |
| Text 3 | `--text-3` | `0.640 0.012 130` #8a8e86 | `0.500 0.012 135` #60655e | Captions, placeholders |
| Text 4 | `--text-4` | `0.500 0.010 130` #61645f | `0.620 0.010 135` #848882 | Disabled only |
| Accent fill | `--accent` | lime-400 #c1f22d | lime-400 | Primary action background |
| Accent ink | `--accent-ink` | `0.170 0.040 135` #071302 | same | Text and icons on accent fill |
| Accent text | `--accent-text` | lime-400 | lime-700 #3f790c | Accent-colored text and glyphs |
| Accent solid | `--accent-solid` | lime-400 | lime-650 #56940d | State fills: meter, switch, check |
| OK | `--ok` | = accent text | = accent text | Completed, success |
| Info | `--info` | `0.800 0.105 235` #76c9f8 | `0.500 0.115 245` #1868a0 | Connecting, queued, notes |
| Warn | `--warn` | `0.830 0.155 82` #f9bc38 | `0.520 0.105 72` #8e5d11 | Stopping, WARNING |
| Error | `--err` | `0.700 0.190 24` #ff6362 | `0.520 0.190 25` #be222a | Failed, ERROR |
| Skip | `--skip` | `0.740 0.035 250` #9badc1 | `0.480 0.030 250` #515f6e | Skipped, neutral state |
| Tag rename | `--tag-rename` | `0.800 0.100 195` #65d2d2 | `0.480 0.080 195` #086b6c | `[RENAME]` |
| Tag filter | `--tag-filter` | `0.780 0.085 325` #d4a5d6 | `0.480 0.110 325` #7c467f | `[FILTER]` |

Accent ramp `--lime-200..900` (one hue family, perceptual steps): 200 #e0fa9d, 300 #d1f665,
**400 #c1f22d**, 500 #a0db1d, 600 #74b417, 650 #56940d, 700 #3f790c, 900 #1a3911. Gradients
run across ramp stops (300 -> 500), never one hex at varied opacity. Every status color has a
`-soft` fill (14% mix) for badges and callouts.

Raw color literals outside `tokens.css`: only `<meta name="theme-color">` in `index.html`
(the browser needs it before CSS loads; `app.js` then keeps it equal to `--canvas`) and the
favicon SVG (lime-400 on accent ink).

Measured contrast: text-1/2/3 on surface-1 = 17.2 / 10.2 / 5.7 (dark), 17.8 / 9.8 / 5.9
(light); accent ink on accent = 14.5; lime-700 on light surface = 5.3; lime-650 = 3.7.

### Rules
- One accent. Lime marks the primary action (background, not glyph), live progress and
  success. Nothing decorative carries it.
- Selected, focused and active states use washes, tonal lift and a glyph or icon weight
  change. Never a colored side border. `:focus-visible` rings are the only colored edge.
- Status is never color alone: every state also has a label and an icon or glyph.
- No pure black or white. No color outside this table; extend the table first.

## 3. Typography

| Level | Token | Size | Weight | Width | Line | Tracking | Usage |
|---|---|---|---|---|---|---|---|
| Hero | `--fs-hero` | clamp(4.25rem, 9.2vw + 1.6rem, 8.75rem) | 700 | 118 | 0.86 | -0.045em | Deck numeral |
| Display | `--fs-display` | clamp(2.5rem, 4vw + 1.5rem, 4.5rem) | 700 | 116 | 0.95 | -0.035em | Deck state line |
| Title | `--fs-title` | clamp(1.375rem, 1.2vw + 1rem, 1.625rem) | 650 | 112 | 1.15 | -0.02em | View title (h1) |
| Metric | `--fs-metric` | 1.75rem | 600 | 106 | 1.1 | -0.02em | Readout values |
| Lead | `--fs-lead` | 1.25rem | 650 | 104-108 | 1.25 | -0.015em | Dialog titles, counts, names |
| H2 | `--fs-h2` | 1rem | 600 | 104 | 1.3 | -0.005em | Panel titles |
| Body | `--fs-body` | 0.875rem | 400 | 100 | 1.55 | 0.005em | Default text |
| Small | `--fs-sm` | 0.8125rem | 400 | 100 | 1.5 | 0.01em | Help, table cells |
| XS | `--fs-xs` | 0.75rem | 500 | 100 | 1.4 | 0.02em | Meta, chips |
| Micro | `--fs-micro` | 0.6875rem | 500 | mono 87.5 | 1.3 | 0.08em, uppercase | Readout labels |
| Data | `--fs-data` | 0.75rem | 400 | mono 87.5 | 1.6 | 0 | File names, ids, logs |

### Font stack
- Sans: `"Mona Sans"` (variable, wght 200-900, wdth 75-125, OFL) then `"Segoe UI Variable
  Text", "Segoe UI", system-ui, sans-serif`. Latin only, so Cyrillic human text falls back.
- Mono: `"Martian Mono"` (variable, wght 100-800, wdth 75-112.5, OFL, Latin + Cyrillic) then
  `ui-monospace, "Cascadia Mono", Consolas, monospace`.
- Files are vendored in `fonts/` with their OFL texts and loaded with `font-display: swap`
  and `unicode-range`, so the Cyrillic file is fetched only when Cyrillic appears.

### Rules
- Two families. Width is the display lever: wide (112-118) for numerals and titles only.
- Display figures and data figures differ on purpose. The deck numeral uses proportional
  figures: the whole percent is huge, the decimal and the unit sit small (0.42em) on the
  same baseline in a fixed-width slot, so "5.0%" reads as one number and a changing digit
  never moves the big one. Every other number is tabular (`.num`); Mona Sans tabular
  figures carry a slashed zero, kept as the data look.
- Body text never below 14px. Icons come in 12, 14, 16, 18, 20 and 22px.
- Machine data is monospace and truncates in the middle of the row, never wraps a layout.
  Paths that must wrap (`pathText()`, class `.path`) break only after `/` and `\` through a
  `<wbr>` per separator; `overflow-wrap: break-word` is the last resort for a single folder
  name wider than the line. `overflow-wrap: anywhere` is never set on a path.
- Sizes: MB with one decimal, GB above 1024 MB, KB below 0.1 MB. A total the API has already
  rounded to 0.0 for a non-empty set renders as `<0.1 MB`, never `0.0 MB`.
- Micro labels are a readout convention for label-above-value pairs, not section eyebrows.

## 4. Spacing & Layout

Base unit 4px: `--space-1` 4, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40,
`-12` 48, `-16` 64. Shell gutter `--gutter` 8px (islands), page padding `--page-pad`
clamp(12px, 2.2vw, 28px), content max width `--content-max` 1240px, control heights
`--control-sm` 28, `--control-md` 36, `--control-lg` 44 (minimum touch target 44 on compact).

### Shell
- `fixed-sidenav-shell`: `.app` is a grid, `block-size: 100dvb`, columns `auto minmax(0,1fr)`.
  The sidebar is an island panel; the main column is a `scroll-body-shell` with rows
  topbar / view / dock.
- Scroll ownership: `.view` owns vertical scroll (`min-block-size: 0; overflow: auto`).
  Logs switches `.view` to `overflow: hidden` and `.log-pane` owns the scroll. No other
  nested scrollers.
- Layout states: `wide` >= 1100px full sidebar (232px); `rail` 768-1099px icon rail (64px);
  `compact` < 768px no sidebar, a floating bottom tab bar, single column everywhere.
- Dashboard columns (`.dash-cols`, `data-layout`): idle = configured channels in scan order
  beside the primer as one column of steps; active = worker lanes beside channels; ended =
  channels beside the last session card. After a stop, the channel remembered as current
  during the run is listed as partially scanned, not as unreached.
- Library: the channel table runs full width; recent downloads and the setup card share a
  row, and the setup card is sticky so a long list never leaves it stranded.
- Account: the sign-in card beside three help notes; signed in, the notes give way to a
  compact session panel (session file, API ID, hash hint, Settings link). Log out is disabled
  with a note while a session runs, like Cleanup and Save.
- Grids use `repeat(auto-fit, minmax(min(X, 100%), 1fr))`; scrolling children carry
  `min-block-size: 0`; long strings carry `min-inline-size: 0` plus ellipsis or `anywhere`.

## 5. Components

Every interactive primitive has default, hover, active, `:focus-visible`, disabled states.
The hidden route `#/kit` renders all of them as the primitive showcase.

- **Shell nav item**: icon + label link. Current page = wash-2 fill, text-1, fill-weight icon,
  `aria-current="page"`. Rail state hides labels (kept for screen readers). Tab bar on compact.
- **Button**: `primary` (accent fill, accent ink), `secondary` (surface-2 + line-strong),
  `ghost`, `danger` (err-soft fill, err text). Sizes sm / md / lg. Radius sm. Busy state keeps
  the label and width and swaps the icon for a spinner; `aria-busy`. Press scales to 0.98.
- **Transport button**: pill, radius full, with a nested round icon well (button in button).
  Only Start and Stop use it. Rule: transport keys are round, every other control is radius sm.
  Stop shows `aria-busy` (spinner in the well, label "Stopping") while the stop completes;
  it is never disabled, so focus stays on it. When the deck swaps Start for Stop or back,
  focus moves to the new transport if the old one had it.
- **Icon button**: square 36 or 28, always has `aria-label`.
- **Field**: label above, control, help below, error below with icon; `aria-describedby`
  names the help and, while shown, the error element; invalid sets `aria-invalid`. Numeric
  and range fields are checked on input (once they differ from the saved value) and on blur,
  not only on save. Inputs are surface-2 wells with line-strong edge, unit suffix slot, 36px
  high. No placeholder-as-label.
- **Switch**: `button[role=switch]`, 40x24 track, heavy spring thumb, accent-solid when on.
- **Checkbox**: native input restyled, 18px box, check glyph, accent-solid when checked.
- **Segmented**: radio group in a surface-inset well; the selected segment lifts one notch.
- **Toggle chip**: `aria-pressed` filter chip with optional count (log levels).
- **Tag input**: chips inside a field well; Enter or comma adds, Backspace removes the last.
- **List editor**: ordered rows with index, value, move up, move down, remove; add row below.
- **State badge**: pill with glyph + label for idle, connecting, running, stopping, finished,
  stopped, failed. Running shows the EQ glyph.
- **Chip**: compact pill for global status in the top bar (session, account, server).
- **Keycap**: surface-3 gradient key with bezel, radius xs. Worker tags and shortcut hints.
- **Panel**: surface-1, radius lg, hairline, bezel highlight. Optional header with h2 and
  actions. Used when a group needs a boundary; otherwise plain spacing.
- **Deck**: the hero. Double bezel: outer shell (wash, hairline, 6px padding, radius xl) and
  an inner core (radius xl minus 6px, bezel highlight, live glow layer).
- **Readout strip**: one panel divided by hairlines; each cell is micro label, metric value,
  unit. Replaces a row of separate stat cards.
- **Waveform meter**: see Section 6. `role="progressbar"` with `aria-valuenow`.
- **EQ glyph**: 4 bars, animated only while live, static otherwise. Always `aria-hidden`.
- **Data table**: real `<table>` at wide; rows restack into label/value pairs on compact.
  One hairline between rows, no zebra, numeric columns right-aligned and tabular.
- **Callout**: soft status fill + icon + text + optional action. No side stripe.
- **Toast**: surface-4 card, icon, title, message, dismiss. `role="status"` or `alert`.
- **Dialog**: native `<dialog>`, radius xl, scrim. Buttons name the outcome; initial focus
  lands on the safe (cancel) button so Enter never fires the destructive outcome, Escape
  cancels, and focus returns to the opener on close.
- **Skeleton**: surface-2 blocks shaped like the final layout; shown only after 300 ms.
- **Empty state**: icon well, one line title, one line of how to fill it, optional action.
- **Log row**: time, level, message with leading marker tags; WARNING and ERROR rows get a
  status wash across the whole row. The pane ends with a tail cursor (EQ glyph + "Live tail")
  while live and non-empty; it hides when paused, offline or empty. The toolbar count reads
  "N lines", or "N shown of M" while filters hide rows; the buffer cap is a tooltip only.
- **Stepper**: numbered steps with done / current / upcoming states for the sign-in flow.
- **Setting row**: label + description left, control right; stacks on compact. Grouped in a
  panel with hairlines between rows.
- **Save bar**: sticky bar that rises when the form is dirty: change count, Reset, Save. It
  spans the form column (not the index). While open, the form gets bottom padding and the
  scroller `scroll-padding-block-end`, so a focused row is never left under the bar.
- **Last session card**: times, file limit, effective workers (override, else the count seen
  while running, else the configured value, with "(configured)") and scan results. Counts,
  rates and "not processed" live only in the readout strip above it.
- **Dock**: slim session transport shown on every view except the dashboard while a session
  is active: state, percent, progress line, counts, Stop.

## 6. Motion & Interaction

| Token | Value | Usage |
|---|---|---|
| `--dur-1` | 120ms | Press, hover wash |
| `--dur-2` | 200ms | Toggles, segment change, fades |
| `--dur-3` | 360ms | Dialog, toast, view enter |
| `--dur-4` | 560ms | Theme reveal, deck glow, dock and save bar |
| `--dur-poll` | 1000ms linear | Progress motion, matched to the 1 s poll |
| `--ease-out` | cubic-bezier(0.32, 0.72, 0, 1) | Default (soft-skill fluid curve) |
| `--ease-spring` | `linear()` from spring 420 / 34 / 0.75 | Toast, dialog, bars (no overshoot) |
| `--ease-thumb` | `linear()` from spring 800 / 80 / 4 | Switch thumb (4% overshoot) |

Mechanisms:
- **Waveform meter (novel)**: 96 bars (48 on compact) with fixed pseudo-random heights. A
  dim base layer and a lime layer share the bars; the lime layer is revealed by two opposing
  `translateX` transforms driven by `--p` (0..1), so the reveal is compositor-only and moves
  at an even pace over `--dur-poll`. While the session is running, the five bars behind the
  play head animate `scaleY` (the equalizer). Unknown total (connecting) shows a sweep across
  the dim bars instead of a fill. Reduced motion: no dance, no sweep, the fill still moves.
- **EQ glyph (novel)**: four bars, `scaleY` keyframes at 0.7-1.1 s with staggered phase, only
  while `data-live` is set. Reduced motion: static bars; the label carries the state.
- **Atmosphere**: static layered radial light on the canvas plus a static grain tile
  (react-bits `Noise`, retrofitted to one frame). The deck glow fades in while live.
- **Theme toggle**: `document.startViewTransition` with a circular `clip-path` reveal from
  the toggle (beui `theme-toggle`). Unsupported or reduced motion: instant swap.
- **Toasts**: rise from the bottom edge with `--ease-spring`, leave with a 180 ms fade; 4.2 s
  dwell, errors 8 s; timers pause on hover and focus (beui `animated-toast-stack`).
- **Dialog**: scrim fade, panel 0.96 -> 1 scale with spring; exits the way it came.
- **Feedback thresholds**: press feedback same frame; skeletons only after 300 ms; success
  is shown by the changed state itself, toasts are for outcomes not visible in place;
  failures are reported next to the control that caused them.

Rules: motion animates only `transform`, `opacity` and `filter` (plus `clip-path` inside the
theme view transition); colors and backgrounds may cross-fade over `--dur-1` or `--dur-2`;
layout properties never animate. No scroll listeners on `window`: section spying uses
`IntersectionObserver` on a reading line 40% down the scroller (the last section once the
end sentinel is in view; an index click pins its section until the next scroll), and the
log pane listens to its own scroll only to hold the tail.
Every animation has a `prefers-reduced-motion` path that reduces to opacity or nothing
(verified: zero running animations on the live dashboard under reduced motion).

## 7. Depth & Surface

Strategy: **mixed** - a tonal ladder with a hairline bezel for everything in the page, real
shadows only for layers that float above it.

| Level | Recipe | Usage |
|---|---|---|
| Panel | surface-1 + 1px `--line` + inset 0 1px 0 `--bezel` | Sidebar, panels |
| Deck | outer shell (wash-1, `--line`, 6px pad) + core (gradient surface-2 -> surface-1, bezel, glow layer) | Hero |
| Well | surface-inset + inset 0 1px 2px shadow | Meter, log pane, segmented |
| Key | gradient surface-3 -> surface-2 + bezel + 1px bottom edge | Keycaps, thumbs |
| Overlay | surface-4 + `--line-strong` + `--shadow-overlay` | Toasts, dialogs, save bar |

| Token | Value | Usage |
|---|---|---|
| `--radius-xs` | 4px | Keycaps, tags, bars |
| `--radius-sm` | 8px | Buttons, inputs, chips rows |
| `--radius-md` | 12px | Toasts, callouts, inner groups |
| `--radius-lg` | 16px | Panels, deck core |
| `--radius-xl` | 22px | Deck shell, sidebar island, dialogs, tab bar |
| `--radius-full` | 999px | Pills, badges, transport buttons, switch |

Nested corners are concentric (deck core = xl minus the 6px shell). Z scale: `--z-sticky` 20
(save bar), `--z-toast` 50, `--z-grain` 60; dialogs use the browser top layer. The scrolling
view fades out under the top bar through a 12px `mask-image` instead of a hard edge.

## 8. Accessibility Constraints & Accepted Debt

### Constraints
- WCAG 2.2 AA: body text >= 4.5:1, large text and UI state indicators >= 3:1, in both themes.
- Full keyboard reach: skip link, visible `:focus-visible` ring (2px accent text + 2px
  offset), focus moves to the view on route change, dialogs trap focus natively.
- Live regions: session state changes and toasts are announced; the log pane is `role="log"`.
- `prefers-reduced-motion` reduces every animation to opacity or nothing (Section 6).
- Reflow: one readable column at 375px, no horizontal page scroll; targets >= 44px on compact.
- Destructive or irreversible actions (stop, clean up, log out) confirm with named outcomes.

### Accepted Debt
| Item | Location | Why accepted | Owner / Exit |
|---|---|---|---|
| No Lighthouse run | whole UI | No Playwright/Lighthouse without npm in this task | Run once the real server exists |
| Sans has no Cyrillic | `fonts/` | Mona Sans is Latin only; data is mono (Cyrillic covered) | Swap face if Cyrillic copy is added |
| Per-file progress absent | Dashboard lanes | API exposes only name and size per worker | Add when the backend reports bytes |
| Lime fill on light theme is 1.3:1 against the page | Primary button, light | Label is 14.5:1 and an inset edge marks the shape | Revisit if light becomes default |
