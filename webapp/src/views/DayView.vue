<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { api } from "../api";
import PlanPreview from "../components/PlanPreview.vue";
import TaskRow from "../components/TaskRow.vue";
import { addDays, dayLabel, shortDay, timeOf } from "../dates";
import { focusDay, meta, showToast, version } from "../store";
import type { CalendarEvent, DayView, Task } from "../types";

const props = defineProps<{ day: string }>();
const emit = defineEmits<{ "update:day": [day: string] }>();

const data = ref<DayView | null>(null);
const showDone = ref(false);
const planning = ref(false);
const now = ref(new Date());

const today = computed(() => meta.value?.today ?? "");
const isToday = computed(() => props.day === today.value);

type Item = { kind: "event"; at: string; end: string; event: CalendarEvent } | { kind: "task"; at: string; task: Task };

const allDay = computed(() => data.value?.events.filter((e) => e.all_day) ?? []);
const open = computed(() => data.value?.tasks.filter((t) => t.status === "todo") ?? []);
const done = computed(() => data.value?.tasks.filter((t) => t.status === "done") ?? []);
const anytime = computed(() => open.value.filter((t) => !t.due_time));
const timeline = computed<Item[]>(() => {
  const items: Item[] = [
    ...(data.value?.events ?? [])
      .filter((e) => !e.all_day)
      .map((e) => ({ kind: "event" as const, at: timeOf(e.start), end: timeOf(e.end), event: e })),
    ...open.value.filter((t) => t.due_time).map((t) => ({ kind: "task" as const, at: t.due_time!, task: t })),
  ];
  return items.sort((a, b) => a.at.localeCompare(b.at));
});
const nowTime = computed(() => now.value.toTimeString().slice(0, 5));
/** Index in the timeline before which the "now" line goes (-1 = not today). */
const nowIndex = computed(() => {
  if (!isToday.value) return -1;
  const i = timeline.value.findIndex((it) => it.at > nowTime.value);
  return i === -1 ? timeline.value.length : i;
});

async function load() {
  try {
    data.value = await api.day(props.day);
  } catch {
    showToast("Couldn't load the day");
  }
}

watch(() => [props.day, version.value], load, { immediate: true });
watch(
  () => props.day,
  (d) => (focusDay.value = d),
  { immediate: true },
);

let clock = 0;
onMounted(() => (clock = window.setInterval(() => (now.value = new Date()), 60_000)));
onBeforeUnmount(() => window.clearInterval(clock));
</script>

<template>
  <section>
    <header class="nav">
      <button class="icon" aria-label="Previous day" @click="emit('update:day', addDays(day, -1))">‹</button>
      <button class="nav-title" @click="emit('update:day', today)">
        <strong>{{ dayLabel(day, today) }}</strong>
        <small v-if="dayLabel(day, today) !== shortDay(day)">{{ shortDay(day) }}</small>
      </button>
      <button class="icon" aria-label="Next day" @click="emit('update:day', addDays(day, 1))">›</button>
    </header>

    <p v-if="!data" class="hint loading">Loading…</p>
    <template v-else>
      <div v-if="allDay.length" class="all-day">
        <span v-for="e in allDay" :key="e.id" class="pill">📅 {{ e.title }}</span>
      </div>

      <div v-if="data.overdue.length" class="group overdue">
        <h4>Overdue</h4>
        <TaskRow v-for="t in data.overdue" :key="t.id" :task="t" show-date />
      </div>

      <div class="group">
        <div class="group-head">
          <h4>Schedule</h4>
          <button v-if="open.length" class="link" @click="planning = true">✨ Smart plan</button>
        </div>
        <p v-if="!timeline.length" class="hint">No meetings or timed tasks.</p>
        <div class="timeline">
          <template v-for="(it, i) in timeline" :key="it.kind + (it.kind === 'event' ? it.event.id : it.task.id)">
            <div v-if="i === nowIndex" class="now-line"><span>{{ nowTime }}</span></div>
            <div class="slot">
              <div class="slot-time">{{ it.at }}</div>
              <a
                v-if="it.kind === 'event'"
                class="event"
                :href="it.event.link ?? undefined"
                target="_blank"
                rel="noopener"
              >
                <span class="title">{{ it.event.title }}</span>
                <span class="details">{{ it.at }}–{{ it.end }}</span>
              </a>
              <TaskRow v-else :task="it.task" :show-time="false" />
            </div>
          </template>
          <div v-if="nowIndex === timeline.length && timeline.length" class="now-line"><span>{{ nowTime }}</span></div>
        </div>
      </div>

      <div class="group">
        <h4>Anytime</h4>
        <p v-if="!anytime.length" class="hint">Nothing unscheduled.</p>
        <TaskRow v-for="t in anytime" :key="t.id" :task="t" />
      </div>

      <div v-if="done.length" class="group">
        <button class="link" @click="showDone = !showDone">
          {{ showDone ? "Hide" : "Show" }} {{ done.length }} done
        </button>
        <template v-if="showDone">
          <TaskRow v-for="t in done" :key="t.id" :task="t" />
        </template>
      </div>
    </template>

    <PlanPreview v-if="planning" :day="day" @close="planning = false" />
  </section>
</template>
