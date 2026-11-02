<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";

import { completeTask, createTask, dropTask, updateTask } from "../actions";
import { addDays, parseDay, weekdayIndex } from "../dates";
import { meta, sheet } from "../store";
import { useBackButton } from "../telegram";
import type { Task, TaskInput } from "../types";

const props = defineProps<{ task: Task | null; day: string | null }>();

const BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
type Repeat = "none" | "daily" | "weekdays" | "weekly" | "monthly" | "custom";

const today = computed(() => meta.value?.today ?? "");

function ruleFor(repeat: Repeat, day: string): string | null {
  switch (repeat) {
    case "daily":
      return "FREQ=DAILY";
    case "weekdays":
      return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
    case "weekly":
      return `FREQ=WEEKLY;BYDAY=${BYDAY[weekdayIndex(day)]}`;
    case "monthly":
      return `FREQ=MONTHLY;BYMONTHDAY=${parseDay(day).getDate()}`;
    case "custom":
      return props.task?.recurrence_rule ?? null;
    default:
      return null;
  }
}

function repeatFor(rule: string | null, day: string): Repeat {
  if (!rule) return "none";
  for (const r of ["daily", "weekdays", "weekly", "monthly"] as const) if (ruleFor(r, day) === rule) return r;
  return "custom";
}

const t = props.task;
const form = reactive({
  title: t?.title ?? "",
  notes: t?.notes ?? "",
  date: t ? (t.due_date ?? "") : (props.day ?? ""),
  time: t?.due_time ?? "",
  priority: t?.priority ?? 2,
  est: t?.est_minutes ?? 0,
  repeat: repeatFor(t?.recurrence_rule ?? null, t?.due_date ?? today.value) as Repeat,
});
const saving = ref(false);
const titleEl = ref<HTMLTextAreaElement | null>(null);

const nextMonday = computed(() => addDays(today.value, 7 - weekdayIndex(today.value)));
const quickDates = computed(() => [
  { label: "Today", value: today.value },
  { label: "Tomorrow", value: addDays(today.value, 1) },
  { label: "Next week", value: nextMonday.value },
  { label: "Inbox", value: "" },
]);

function close() {
  sheet.value = null;
}

async function save() {
  if (!form.title.trim()) {
    titleEl.value?.focus();
    return;
  }
  // A repeating task needs a first day.
  if (form.repeat !== "none" && !form.date) form.date = today.value;
  const values: TaskInput = {
    title: form.title.trim(),
    notes: form.notes.trim() || null,
    due_date: form.date || null,
    due_time: form.time || null,
    priority: form.priority as Task["priority"],
    est_minutes: form.est || null,
    recurrence_rule: ruleFor(form.repeat, form.date || today.value),
  };

  saving.value = true;
  let ok: boolean;
  if (!t) {
    ok = await createTask(values);
  } else {
    // Send only what changed, so the history doesn't record moves that didn't happen.
    const patch: TaskInput = {};
    for (const key of Object.keys(values) as (keyof TaskInput)[]) {
      if (values[key] !== t[key]) (patch as Record<string, unknown>)[key] = values[key];
    }
    ok = Object.keys(patch).length === 0 || (await updateTask(t, patch));
  }
  saving.value = false;
  if (ok) close();
}

async function done() {
  if (t) await completeTask(t);
  close();
}

async function tomorrow() {
  if (t && (await updateTask(t, { due_date: addDays(today.value, 1) }))) close();
}

async function drop() {
  if (t && (await dropTask(t))) close();
}

const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
let releaseBack = () => {};
onMounted(async () => {
  releaseBack = useBackButton(close);
  window.addEventListener("keydown", onKey);
  if (!t) {
    await nextTick();
    titleEl.value?.focus();
  }
});
onBeforeUnmount(() => {
  releaseBack();
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div class="backdrop" @click.self="close">
    <form class="sheet" @submit.prevent="save">
      <textarea
        ref="titleEl"
        v-model="form.title"
        class="title-input"
        rows="2"
        maxlength="500"
        placeholder="What needs doing?"
        @keydown.enter.exact.prevent="save"
      />

      <div class="field">
        <span class="label">Day</span>
        <div class="chips">
          <button
            v-for="q in quickDates"
            :key="q.label"
            type="button"
            class="chip"
            :class="{ active: form.date === q.value }"
            @click="form.date = q.value"
          >
            {{ q.label }}
          </button>
          <input v-model="form.date" type="date" class="date-input" />
        </div>
      </div>

      <div class="field row">
        <label class="half">
          <span class="label">Time</span>
          <span class="inline">
            <input v-model="form.time" type="time" />
            <button v-if="form.time" type="button" class="link" @click="form.time = ''">clear</button>
          </span>
        </label>
        <label class="half">
          <span class="label">Takes</span>
          <select v-model.number="form.est">
            <option :value="0">—</option>
            <option v-for="m in [15, 30, 45, 60, 90, 120, 180, 240]" :key="m" :value="m">
              {{ m < 60 ? `${m} min` : `${m / 60} h` }}
            </option>
          </select>
        </label>
      </div>

      <div class="field row">
        <div class="half">
          <span class="label">Priority</span>
          <div class="segmented">
            <button
              v-for="p in [1, 2, 3] as const"
              :key="p"
              type="button"
              :class="[`prio-${p}`, { active: form.priority === p }]"
              @click="form.priority = p"
            >
              {{ { 1: "High", 2: "Normal", 3: "Low" }[p] }}
            </button>
          </div>
        </div>
        <label class="half">
          <span class="label">Repeat</span>
          <select v-model="form.repeat">
            <option value="none">Never</option>
            <option value="daily">Every day</option>
            <option value="weekdays">Weekdays</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option v-if="task?.recurrence_rule && form.repeat === 'custom'" value="custom">
              {{ task.repeat_label }} (keep)
            </option>
          </select>
        </label>
      </div>

      <textarea v-model="form.notes" class="notes" rows="2" maxlength="5000" placeholder="Notes" />

      <div class="actions">
        <template v-if="task">
          <button type="button" class="secondary" @click="done">✓ Done</button>
          <button type="button" class="secondary" @click="tomorrow">Tomorrow</button>
          <button type="button" class="secondary danger" @click="drop">Drop</button>
        </template>
        <button type="submit" class="primary" :disabled="saving">{{ task ? "Save" : "Add" }}</button>
      </div>
    </form>
  </div>
</template>
