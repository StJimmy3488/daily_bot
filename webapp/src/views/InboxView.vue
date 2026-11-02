<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { updateTask } from "../actions";
import { api } from "../api";
import TaskRow from "../components/TaskRow.vue";
import { addDays } from "../dates";
import { focusDay, meta, showToast, version } from "../store";
import type { Task } from "../types";

const tasks = ref<Task[] | null>(null);
const today = computed(() => meta.value?.today ?? "");

async function load() {
  try {
    tasks.value = await api.inbox();
  } catch {
    showToast("Couldn't load the inbox");
  }
}

watch(version, load, { immediate: true });
focusDay.value = null;

async function schedule(task: Task, day: string) {
  if (await updateTask(task, { due_date: day })) showToast(day === today.value ? "Moved to today" : "Moved to tomorrow");
}
</script>

<template>
  <section>
    <header class="nav">
      <div class="nav-title">
        <strong>Inbox</strong>
        <small>Tasks without a day</small>
      </div>
    </header>
    <p v-if="!tasks" class="hint loading">Loading…</p>
    <p v-else-if="!tasks.length" class="empty">Inbox zero 📭</p>
    <div v-for="t in tasks ?? []" :key="t.id" class="inbox-item">
      <TaskRow :task="t" />
      <div class="quick">
        <button class="chip" @click="schedule(t, today)">Today</button>
        <button class="chip" @click="schedule(t, addDays(today, 1))">Tomorrow</button>
      </div>
    </div>
  </section>
</template>
