<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { api, ApiError } from "../api";
import { changed, showToast } from "../store";
import { haptic, useBackButton } from "../telegram";
import type { Plan } from "../types";

const props = defineProps<{ day: string }>();
const emit = defineEmits<{ close: [] }>();

const plan = ref<Plan | null>(null);
const error = ref("");
const selected = ref<Set<number>>(new Set());
const applying = ref(false);

const flexible = computed(() => plan.value?.blocks.filter((b) => !b.fixed && b.task_id !== null) ?? []);

function toggle(id: number) {
  const s = new Set(selected.value);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  selected.value = s;
  haptic.select();
}

async function apply() {
  if (!plan.value) return;
  applying.value = true;
  try {
    const items = flexible.value
      .filter((b) => selected.value.has(b.task_id!))
      .map((b) => ({ task_id: b.task_id!, time: b.start }));
    await api.applyPlan(plan.value.date, items);
    haptic.success();
    showToast(`Times set for ${items.length} task(s) — reminders scheduled`);
    changed();
    emit("close");
  } catch (e) {
    showToast(e instanceof ApiError ? e.message : "Network error — try again");
  } finally {
    applying.value = false;
  }
}

let releaseBack = () => {};
onMounted(async () => {
  releaseBack = useBackButton(() => emit("close"));
  try {
    plan.value = await api.plan(props.day);
    selected.value = new Set(flexible.value.map((b) => b.task_id!));
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "Network error — try again";
  }
});
onBeforeUnmount(() => releaseBack());
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="sheet">
      <h3>Smart plan</h3>
      <p v-if="error" class="hint">{{ error }}</p>
      <p v-else-if="!plan" class="hint loading">Fitting your tasks around your meetings…</p>
      <template v-else>
        <p v-if="plan.note" class="note">{{ plan.note }}</p>
        <p v-if="!plan.blocks.length" class="hint">No free working time left on this day.</p>
        <ul class="plan">
          <li
            v-for="(b, i) in plan.blocks"
            :key="i"
            :class="{ fixed: b.fixed, off: !b.fixed && !selected.has(b.task_id!) }"
            @click="!b.fixed && toggle(b.task_id!)"
          >
            <span class="time">{{ b.start }}–{{ b.end }}</span>
            <span class="what">{{ b.task_id === null ? "📅 " : "" }}{{ b.title }}</span>
            <span v-if="!b.fixed" class="tick">{{ selected.has(b.task_id!) ? "☑" : "☐" }}</span>
          </li>
        </ul>
        <p v-if="plan.unplaced.length" class="hint">
          Didn't fit: {{ plan.unplaced.map((t) => t.title).join(", ") }}
        </p>
        <div class="actions">
          <button type="button" class="secondary" @click="emit('close')">Close</button>
          <button v-if="flexible.length" class="primary" :disabled="applying || !selected.size" @click="apply">
            Set {{ selected.size }} time(s)
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
