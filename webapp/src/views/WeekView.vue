<script setup lang="ts">
import Sortable from "sortablejs";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { updateTask } from "../actions";
import { api } from "../api";
import TaskRow from "../components/TaskRow.vue";
import { addDays, shortDay, timeOf } from "../dates";
import { focusDay, meta, sheet, showToast, version } from "../store";
import { haptic } from "../telegram";
import type { Week } from "../types";

const emit = defineEmits<{ openDay: [day: string] }>();

const today = computed(() => meta.value?.today ?? "");
const start = ref(today.value); // rolling: the next 7 days, not the calendar week
const data = ref<Week | null>(null);
const lists = ref<HTMLElement[]>([]);
let sortables: Sortable[] = [];

async function load() {
  try {
    data.value = await api.week(start.value);
  } catch {
    showToast("Couldn't load the week");
    return;
  }
  await nextTick();
  bindDrag();
}

/** Drag a task onto another day to move it there. */
function bindDrag() {
  sortables.forEach((s) => s.destroy());
  sortables = lists.value.map((el) =>
    Sortable.create(el, {
      group: "week",
      animation: 150,
      delay: 200, // long-press on touch, so scrolling still works
      delayOnTouchOnly: true,
      draggable: ".task-row:not(.done)",
      ghostClass: "drag-ghost",
      onChoose: () => haptic.tap(),
      onEnd: (evt) => {
        const from = evt.from.dataset.date!;
        const to = evt.to.dataset.date!;
        // Put the DOM back: Vue owns it and re-renders from data.
        evt.from.insertBefore(evt.item, evt.from.children[evt.oldIndex!] ?? null);
        if (from === to || !data.value) return;
        const task = data.value.days.flatMap((d) => d.tasks).find((t) => t.id === Number(evt.item.dataset.id));
        if (!task) return;
        // Optimistic move, then the server's answer reloads the week.
        const src = data.value.days.find((d) => d.date === from)!;
        const dst = data.value.days.find((d) => d.date === to)!;
        src.tasks = src.tasks.filter((t) => t.id !== task.id);
        dst.tasks = [...dst.tasks, { ...task, due_date: to }];
        updateTask(task, { due_date: to }).then((ok) => ok && showToast(`Moved to ${shortDay(to)}`));
      },
    }),
  );
}

watch(() => [start.value, version.value], load, { immediate: true });
watch(start, (s) => (focusDay.value = s), { immediate: true });
onBeforeUnmount(() => sortables.forEach((s) => s.destroy()));
</script>

<template>
  <section>
    <header class="nav">
      <button class="icon" aria-label="Previous week" @click="start = addDays(start, -7)">‹</button>
      <button class="nav-title" @click="start = today">
        <strong>{{ shortDay(start) }} – {{ shortDay(addDays(start, 6)) }}</strong>
        <small>Hold a task and drag it to another day</small>
      </button>
      <button class="icon" aria-label="Next week" @click="start = addDays(start, 7)">›</button>
    </header>

    <p v-if="!data" class="hint loading">Loading…</p>
    <div v-for="d in data?.days ?? []" :key="d.date" class="day-card" :class="{ today: d.date === today, past: d.date < today }">
      <div class="day-head">
        <button class="link day-name" @click="emit('openDay', d.date)">
          {{ shortDay(d.date) }}<span v-if="d.date === today" class="badge">today</span>
        </button>
        <button class="icon small" aria-label="Add task" @click="sheet = { mode: 'new', day: d.date }">+</button>
      </div>
      <div v-for="e in d.events" :key="'e' + e.id" class="event-line">
        <span class="time">{{ e.all_day ? "all day" : timeOf(e.start) }}</span> {{ e.title }}
      </div>
      <div ref="lists" class="drop-list" :data-date="d.date">
        <TaskRow v-for="t in d.tasks" :key="t.id" :task="t" />
      </div>
    </div>
  </section>
</template>
