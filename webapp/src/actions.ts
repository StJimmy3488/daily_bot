import { api, ApiError } from "./api";
import { shortDay } from "./dates";
import { changed, showToast } from "./store";
import { confirm, haptic } from "./telegram";
import type { Task, TaskInput } from "./types";

function fail(e: unknown) {
  haptic.error();
  showToast(e instanceof ApiError ? e.message : "Network error — try again");
  changed(); // re-sync with the server
}

export async function completeTask(task: Task) {
  try {
    const { next } = await api.complete(task.id);
    haptic.success();
    changed();
    if (next) {
      showToast(`Done · next on ${shortDay(next.due_date!)}`);
    } else {
      showToast("Done", { label: "Undo", run: () => reopenTask(task) });
    }
  } catch (e) {
    fail(e);
  }
}

export async function reopenTask(task: Task) {
  try {
    await api.reopen(task.id);
    changed();
  } catch (e) {
    fail(e);
  }
}

export async function dropTask(task: Task): Promise<boolean> {
  const repeat = task.recurrence_rule ? " This occurrence only — the series continues." : "";
  if (!(await confirm(`Drop “${task.title}”?${repeat}`))) return false;
  try {
    await api.drop(task.id);
    haptic.tap();
    changed();
    showToast("Dropped", task.recurrence_rule ? undefined : { label: "Undo", run: () => reopenTask(task) });
    return true;
  } catch (e) {
    fail(e);
    return false;
  }
}

export async function updateTask(task: Task, patch: TaskInput): Promise<boolean> {
  try {
    await api.update(task.id, patch);
    changed();
    return true;
  } catch (e) {
    fail(e);
    return false;
  }
}

export async function createTask(input: TaskInput): Promise<boolean> {
  try {
    await api.create(input);
    haptic.success();
    changed();
    return true;
  } catch (e) {
    fail(e);
    return false;
  }
}
