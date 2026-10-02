// Actions shared by the shell and the views.

import { api } from "./api.js";
import { applySession, refreshSession } from "./store.js";
import { confirmDialog, toast } from "./ui.js";

/** Confirms, then asks the server to stop the running session. */
export async function requestStop() {
  const confirmed = await confirmDialog({
    title: "Stop this session?",
    body: [
      "Downloads in progress are cancelled and start from zero next time. Files that already finished stay in the library.",
      "The next session resumes scanning after the last fully processed message.",
    ],
    confirmLabel: "Stop session",
    cancelLabel: "Keep running",
    tone: "err",
    iconName: "stop-fill",
  });
  if (!confirmed) return false;
  try {
    applySession(await api.stopSession());
    return true;
  } catch (error) {
    if (error.code === "idle") {
      toast({ tone: "info", title: "The session already ended" });
      refreshSession();
    } else {
      toast({ tone: "err", title: "Could not stop the session", message: error.message });
    }
    return false;
  }
}
