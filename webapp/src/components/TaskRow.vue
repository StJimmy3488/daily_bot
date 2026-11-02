<script setup lang="ts">
import { computed } from "vue";

import { completeTask, reopenTask } from "../actions";
import { dayLabel } from "../dates";
import { meta, sheet } from "../store";
import type { Task } from "../types";

const props = withDefaults(defineProps<{ task: Task; showDate?: boolean; showTime?: boolean }>(), {
  showDate: false,
  showTime: true,
});

const done = computed(() => props.task.status === "done");
const details = computed(() => {
  const t = props.task;
  const today = meta.value?.today ?? "";
  const parts: string[] = [];
  if (props.showDate && t.due_date) parts.push(dayLabel(t.due_date, today));
  if (props.showTime && t.due_time) parts.push(t.due_time);
  if (t.est_minutes) parts.push(t.est_minutes >= 60 ? `${+(t.est_minutes / 60).toFixed(1)} h` : `${t.est_minutes} min`);
  if (t.repeat_label) parts.push(`↻ ${t.repeat_label}`);
  return parts.join(" · ");
});

function toggle() {
  if (done.value) reopenTask(props.task);
  else completeTask(props.task);
}
</script>

<template>
  <div class="task-row" :class="[`prio-${task.priority}`, { done }]" :data-id="task.id">
    <button class="check" :aria-label="done ? 'Mark as not done' : 'Mark as done'" @click.stop="toggle">
      <span v-if="done">✓</span>
    </button>
    <div class="body" @click="sheet = { mode: 'edit', task }">
      <div class="title">{{ task.title }}</div>
      <div v-if="details" class="details">{{ details }}</div>
    </div>
  </div>
</template>
