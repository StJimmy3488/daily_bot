import { reactive, ref } from "vue";

import type { CalendarEvent, Meta, Task } from "./types";

export const meta = ref<Meta | null>(null);

/** Bumped after every change, so every view reloads what it shows. */
export const version = ref(0);
export const changed = () => version.value++;

export const toast = reactive<{ text: string; action?: { label: string; run: () => void }; timer?: number }>({
  text: "",
});

export function showToast(text: string, action?: { label: string; run: () => void }) {
  window.clearTimeout(toast.timer);
  toast.text = text;
  toast.action = action;
  toast.timer = window.setTimeout(() => (toast.text = ""), action ? 5000 : 2500);
}

/** The task sheet: null = closed, "new" = create (optionally on a given day), or edit a task. */
export const sheet = ref<null | { mode: "new"; day: string | null } | { mode: "edit"; task: Task }>(null);

/** The calendar event being viewed or edited. */
export const eventSheet = ref<CalendarEvent | null>(null);

/** The day the user is looking at; "+" adds tasks there (null in the inbox). */
export const focusDay = ref<string | null>(null);
