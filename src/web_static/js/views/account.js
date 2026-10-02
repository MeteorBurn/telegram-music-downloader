// Account: Telegram sign-in wizard (phone, code, password) and the signed-in user card.

import { api } from "../api.js";
import { h, icon, setAttr, setChildren, setText } from "../dom.js";
import { fullName, initials } from "../format.js";
import { applyAuth, auth, refreshAuth } from "../store.js";
import { button, callout, confirmDialog, empty, iconButton, linkButton, skeleton, withBusy } from "../ui.js";

const STEPS = ["Phone", "Code", "Password"];

// Kept between renders and visits so a rejected number does not have to be typed again.
const memory = { phone: "", notice: null };

/** Friendly copy for every error the auth endpoints can return. */
function describe(error) {
  switch (error.code) {
    case "invalid_phone":
      return { text: "Telegram did not accept that number. Use the international format with the country code, for example +79261234567." };
    case "invalid_code":
      return { text: "That code does not match. Check the newest message from Telegram and enter it again." };
    case "code_expired":
      return { text: "That code has expired. Request a new one with your phone number.", restart: true };
    case "invalid_password":
      return { text: "That password does not match. This is your Telegram two-step verification password, not the login code." };
    case "flood_wait": {
      const seconds = Number(/(\d+)\s*second/.exec(error.message ?? "")?.[1] ?? 0);
      return { text: "Telegram is limiting sign-in attempts for this number.", wait: seconds };
    }
    case "no_pending_login":
      return { text: "This sign-in is no longer active. Start again with your phone number.", restart: true };
    case "busy":
      return { text: "A download session is running. Sign-in changes are available once it ends.", tone: "warn", dashboard: true };
    default:
      if (error.status === 409) return { text: "A download session is running. Sign-in changes are available once it ends.", tone: "warn", dashboard: true };
      return { text: error.message || "Telegram sign-in failed. Try again." };
  }
}

function stepper(current) {
  return h(
    "ol",
    { class: "stepper", "aria-label": "Sign-in steps" },
    STEPS.map((label, index) => {
      const status = index < current ? "done" : index === current ? "current" : "upcoming";
      return h(
        "li",
        { class: "step", "data-status": status, "aria-current": status === "current" ? "step" : null },
        h("span", { class: "step-dot" }, status === "done" ? icon("check-bold") : index + 1),
        h("span", null, label),
      );
    }),
  );
}

export function mount(root) {
  const card = h("section", { class: "panel auth-card", "aria-label": "Telegram account" });
  const notes = h(
    "aside",
    { class: "panel notes", "aria-label": "How sign-in works" },
    h("div", { class: "note" }, icon("key"), h("p", null, h("b", null, "API credentials come first"), "Sign-in uses the API ID and hash from ", h("a", { class: "link", href: "#/settings" }, "Settings"), ".")),
    h("div", { class: "note" }, icon("chat-circle-dots"), h("p", null, h("b", null, "The code arrives in Telegram"), "Telegram sends the login code to devices where you are already signed in.")),
    h("div", { class: "note" }, icon("hard-drive"), h("p", null, h("b", null, "The session stays on this machine"), "It is stored next to the app as telegram.session. Logging out removes it.")),
  );
  root.append(h("div", { class: "page account" }, card, notes));

  let screen = null;
  let credentialsReady = true;
  let disposed = false;
  let countdown = null;
  let errorHost = h("div");

  function stopCountdown() {
    clearInterval(countdown);
    countdown = null;
  }

  function showError(error, field, submit, settled = false) {
    const info = describe(error);
    stopCountdown();
    if (info.restart && !settled) {
      // The pending login is usually gone on the server: the phone step then explains why.
      memory.notice = info.text;
      refreshAuth().then(() => {
        if (disposed || auth.get().status?.state === "unauthorized") return;
        memory.notice = null;
        showError(error, field, submit, true);
      });
      return;
    }
    if (field) {
      setAttr(field, "aria-invalid", "true");
      field.focus();
      field.select?.();
    }
    const text = h("p", null, info.text);
    errorHost.replaceChildren(
      h(
        "div",
        { class: "callout", "data-tone": info.tone ?? "err", role: "alert" },
        icon(info.tone === "warn" ? "warning" : "warning-circle"),
        h("div", { class: "callout-body" }, text),
        info.dashboard && h("div", { class: "callout-actions" }, linkButton({ label: "Open dashboard", href: "#/dashboard", iconName: "arrow-right", size: "sm" })),
        info.restart && h("div", { class: "callout-actions" }, button({ label: "Start over", iconName: "arrow-counter-clockwise", size: "sm", onClick: cancel })),
      ),
    );
    if (info.wait > 0 && submit) {
      let left = info.wait;
      const tick = () => {
        if (left <= 0) {
          stopCountdown();
          submit.disabled = false;
          setText(text, "You can try again now.");
          return;
        }
        setText(text, `${info.text} Try again in ${left} ${left === 1 ? "second" : "seconds"}.`);
        left -= 1;
      };
      submit.disabled = true;
      tick();
      countdown = setInterval(tick, 1000);
    }
  }

  function clearError(field) {
    if (field) setAttr(field, "aria-invalid", null);
    if (!countdown) errorHost.replaceChildren();
  }

  function head(title, lead) {
    return h("div", { class: "auth-head" }, h("h2", { class: "auth-title" }, title), h("p", { class: "auth-lead" }, lead));
  }

  // Screens ---------------------------------------------------------------------------
  function phoneScreen() {
    const input = h("input", {
      class: "input",
      id: "auth-phone",
      type: "tel",
      inputmode: "tel",
      autocomplete: "tel",
      placeholder: "+79261234567",
      "data-size": "lg",
      "data-mono": true,
      "aria-describedby": "auth-phone-help",
      value: memory.phone,
    });
    const submit = button({ label: "Send code", iconName: "paper-plane-tilt", variant: "primary", size: "lg", type: "submit" });
    const form = h(
      "form",
      { class: "auth-form", novalidate: true },
      h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "auth-phone" }, "Phone number"), input, h("p", { class: "field-help", id: "auth-phone-help" }, "International format with the country code.")),
      errorHost,
      h("div", { class: "auth-actions" }, submit),
    );
    input.addEventListener("input", () => {
      memory.phone = input.value;
      clearError(input);
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const digits = input.value.replace(/[\s()-]/g, "");
      const phone = digits.startsWith("+") ? digits : `+${digits}`;
      if (!/^\+\d{8,15}$/.test(phone)) {
        showError({ code: "invalid_phone" }, input, submit);
        return;
      }
      memory.phone = phone;
      withBusy(submit, async () => {
        try {
          applyAuth(await api.authPhone(phone));
        } catch (error) {
          if (!disposed) showError(error, input, submit);
        }
      });
    });
    const warning =
      !credentialsReady &&
      callout({
        tone: "warn",
        title: "Add your API credentials first",
        text: "Telegram sign-in needs the API ID and API hash. They are not set yet.",
        actions: linkButton({ label: "Open Settings", href: "#/settings", iconName: "arrow-right", size: "sm" }),
      });
    const notice = memory.notice && callout({ tone: "info", role: "status", text: memory.notice });
    memory.notice = null;
    setChildren(
      card,
      stepper(0),
      head("Sign in to Telegram", "Enter the phone number of the account that can read your channels. Telegram then sends a login code."),
      warning,
      notice,
      form,
    );
  }

  function codeScreen(status) {
    const input = h("input", {
      class: "input code-input",
      id: "auth-code",
      type: "text",
      inputmode: "numeric",
      autocomplete: "one-time-code",
      maxlength: "8",
      placeholder: "00000",
      "aria-label": "Login code",
    });
    const submit = button({ label: "Confirm code", iconName: "check", variant: "primary", size: "lg", type: "submit" });
    const back = button({ label: "Use a different number", variant: "ghost", size: "lg", onClick: cancel });
    const form = h("form", { class: "auth-form", novalidate: true }, input, errorHost, h("div", { class: "auth-actions" }, submit, back));
    input.addEventListener("input", () => {
      input.value = input.value.replace(/\D/g, "");
      clearError(input);
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (input.value.length < 4) {
        showError({ code: "invalid_code" }, input, submit);
        return;
      }
      withBusy(submit, async () => {
        try {
          applyAuth(await api.authCode(input.value));
        } catch (error) {
          if (!disposed) showError(error, input, submit);
        }
      });
    });
    card.replaceChildren(
      stepper(1),
      head("Enter the login code", ["Telegram sent a code to ", h("span", { class: "mono" }, status.phone_masked ?? "your number"), ". Open Telegram on a device where you are signed in to read it."]),
      form,
    );
    input.focus();
  }

  function passwordScreen() {
    const input = h("input", { class: "input", id: "auth-password", type: "password", autocomplete: "current-password", "data-size": "lg" });
    const reveal = iconButton({ label: "Show the password", iconName: "eye", size: "sm" });
    reveal.classList.add("input-action");
    reveal.addEventListener("click", () => {
      const visible = input.type === "text";
      input.type = visible ? "password" : "text";
      const label = visible ? "Show the password" : "Hide the password";
      reveal.setAttribute("aria-label", label);
      reveal.setAttribute("title", label);
      reveal.replaceChildren(icon(visible ? "eye" : "eye-slash"));
    });
    const submit = button({ label: "Sign in", iconName: "sign-in", variant: "primary", size: "lg", type: "submit" });
    const back = button({ label: "Cancel sign-in", variant: "ghost", size: "lg", onClick: cancel });
    const form = h(
      "form",
      { class: "auth-form", novalidate: true },
      h("div", { class: "field" }, h("label", { class: "field-label", htmlFor: "auth-password" }, "Cloud password"), h("div", { class: "input-wrap", "data-suffix": true, "data-size": "lg" }, input, reveal)),
      errorHost,
      h("div", { class: "auth-actions" }, submit, back),
    );
    input.addEventListener("input", () => clearError(input));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!input.value) {
        showError({ code: "invalid_password" }, input, submit);
        return;
      }
      withBusy(submit, async () => {
        try {
          applyAuth(await api.authPassword(input.value));
        } catch (error) {
          if (!disposed) showError(error, input, submit);
        }
      });
    });
    card.replaceChildren(
      stepper(2),
      head("Two-step verification", "This account is protected by a cloud password. Enter it to finish signing in."),
      form,
    );
    input.focus();
  }

  function authorizedScreen(status) {
    const user = status.user ?? {};
    const logout = button({ label: "Log out", iconName: "sign-out", variant: "danger", onClick: onLogout });
    card.replaceChildren(
      h("span", { class: "state-badge", "data-tone": "ok" }, icon("check-circle-fill"), "Signed in"),
      h(
        "div",
        { class: "user-card" },
        h("div", { class: "avatar", "aria-hidden": "true" }, initials(user)),
        h(
          "div",
          null,
          h("p", { class: "user-name" }, fullName(user)),
          h(
            "p",
            { class: "user-meta mono" },
            user.username && h("span", null, `@${user.username}`),
            user.phone_masked && h("span", null, user.phone_masked),
            user.id && h("span", null, `id ${user.id}`),
          ),
        ),
      ),
      h("p", { class: "auth-lead" }, "Sessions download with this account. Log out to remove the stored Telegram session from this machine."),
      errorHost,
      h("div", { class: "auth-actions" }, logout, linkButton({ label: "Open dashboard", href: "#/dashboard", iconName: "arrow-right", variant: "secondary" })),
    );

    async function onLogout() {
      const confirmed = await confirmDialog({
        title: "Log out of Telegram?",
        body: ["The stored session is removed from this machine.", "Downloads stop working until you sign in again with your phone number and a new login code."],
        confirmLabel: "Log out",
        cancelLabel: "Stay signed in",
        tone: "err",
        iconName: "sign-out",
      });
      if (!confirmed) return;
      withBusy(logout, async () => {
        try {
          applyAuth(await api.authLogout());
        } catch (error) {
          if (!disposed) showError(error, null, null);
        }
      });
    }
  }

  async function cancel(event) {
    const control = event.currentTarget;
    await withBusy(control, async () => {
      try {
        applyAuth(await api.authCancel());
      } catch (error) {
        if (!disposed) showError(error, null, null);
      }
    });
  }

  function render({ status, loaded, error }) {
    let next;
    if (!loaded) next = "loading";
    else if (!status) next = "error";
    else if (status.state === "authorized") next = "authorized";
    else if (status.state === "unauthorized") next = "phone";
    else if (status.state === "code_sent") next = "code";
    else if (status.state === "password_needed") next = "password";
    else next = "unknown";
    if (next === screen && next !== "error") return;
    screen = next;
    stopCountdown();
    errorHost = h("div");

    if (next === "loading") {
      card.replaceChildren(h("div", { class: "skeleton-wrap auth-form", "aria-hidden": "true" }, skeleton("12rem", "1.5rem"), skeleton("70%", "2rem"), skeleton("100%", "2.75rem"), skeleton("8rem", "2.75rem")));
    } else if (next === "error") {
      card.replaceChildren(
        callout({
          tone: "err",
          role: "alert",
          title: "The account status could not be loaded",
          text: error?.message ?? "The local server did not answer.",
          actions: button({ label: "Try again", iconName: "arrow-clockwise", size: "sm", onClick: () => refreshAuth() }),
        }),
      );
    } else if (next === "authorized") {
      authorizedScreen(status);
    } else if (next === "phone") {
      phoneScreen();
    } else if (next === "code") {
      codeScreen(status);
    } else if (next === "password") {
      passwordScreen();
    } else {
      card.replaceChildren(
        empty({
          iconName: "hourglass-medium",
          title: "Account status is on hold",
          text: "Telegram is in use by the running session, so the account is not checked right now. It updates as soon as the session ends.",
          action: linkButton({ label: "Open dashboard", href: "#/dashboard", iconName: "arrow-right", size: "sm" }),
        }),
      );
    }
  }

  const unsubscribe = auth.subscribe(render);
  render(auth.get());
  refreshAuth();

  api
    .config()
    .then((data) => {
      const telegram = data?.config?.telegram ?? {};
      const ready = Boolean(telegram.api_id) && Boolean(telegram.api_hash_set);
      if (!disposed && ready !== credentialsReady) {
        credentialsReady = ready;
        if (screen === "phone") {
          screen = null;
          render(auth.get());
        }
      }
    })
    .catch(() => {
      // The credential hint is optional; sign-in itself reports a real failure.
    });

  return () => {
    disposed = true;
    stopCountdown();
    unsubscribe();
  };
}
