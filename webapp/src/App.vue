<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api, ApiError } from "./api";
import TaskSheet from "./components/TaskSheet.vue";
import { focusDay, meta, sheet, toast } from "./store";
import { haptic, initData, tg } from "./telegram";
import DayView from "./views/DayView.vue";
import InboxView from "./views/InboxView.vue";
import WeekView from "./views/WeekView.vue";

type Tab = "day" | "week" | "inbox";
const TABS: Tab[] = ["day", "week", "inbox"];
// A link can open a tab directly: /app/#week
const fromHash = location.hash.slice(1) as Tab;
const tab = ref<Tab>(TABS.includes(fromHash) ? fromHash : "day");
const day = ref("");
const fatal = ref("");

function select(t: Tab) {
  tab.value = t;
  haptic.select();
}

function openDay(d: string) {
  day.value = d;
  select("day");
}

function runToastAction() {
  toast.action?.run();
  toast.text = "";
}

onMounted(async () => {
  tg?.ready();
  tg?.expand();
  if (!initData) {
    fatal.value = "Open this from the bot's menu button in Telegram.";
    return;
  }
  try {
    meta.value = await api.meta();
    day.value = meta.value.today;
  } catch (e) {
    fatal.value =
      e instanceof ApiError && (e.status === 401 || e.status === 403)
        ? `${e.message}. Close and reopen the app from the bot.`
        : "Can't reach the planner right now. Try again in a moment.";
  }
});
</script>

<template>
  <div v-if="fatal" class="fatal">{{ fatal }}</div>
  <div v-else-if="!meta" class="fatal hint loading">Loading…</div>
  <template v-else>
    <nav class="tabs">
      <button :class="{ active: tab === 'day' }" @click="select('day')">Day</button>
      <button :class="{ active: tab === 'week' }" @click="select('week')">Week</button>
      <button :class="{ active: tab === 'inbox' }" @click="select('inbox')">Inbox</button>
    </nav>

    <main>
      <DayView v-if="tab === 'day'" v-model:day="day" />
      <WeekView v-else-if="tab === 'week'" @open-day="openDay" />
      <InboxView v-else />
    </main>

    <button class="fab" aria-label="Add task" @click="sheet = { mode: 'new', day: focusDay }">+</button>

    <TaskSheet
      v-if="sheet"
      :key="sheet.mode === 'edit' ? sheet.task.id : 'new'"
      :task="sheet.mode === 'edit' ? sheet.task : null"
      :day="sheet.mode === 'new' ? sheet.day : null"
    />

    <div v-if="toast.text" class="toast">
      <span>{{ toast.text }}</span>
      <button v-if="toast.action" class="link" @click="runToastAction">{{ toast.action.label }}</button>
    </div>
  </template>
</template>
