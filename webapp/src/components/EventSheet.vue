<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

import { deleteEvent, editEvent } from "../actions";
import { addDays, parseDay, shortDay, timeOf } from "../dates";
import { eventSheet, showToast } from "../store";
import { useBackButton } from "../telegram";
import type { CalendarEvent, EventPatch } from "../types";

const props = defineProps<{ event: CalendarEvent }>();
const e = props.event;

const startDay = e.start.slice(0, 10);
const endDay = e.all_day ? addDays(e.end.slice(0, 10), -1) : e.end.slice(0, 10); // all-day end is exclusive
const form = reactive({ title: e.title, day: startDay, start: timeOf(e.start), end: timeOf(e.end) });
const saving = ref(false);

const when = computed(() => {
  if (e.all_day) return startDay === endDay ? `${shortDay(startDay)} · all day` : `${shortDay(startDay)} – ${shortDay(endDay)}`;
  return `${shortDay(startDay)} · ${timeOf(e.start)}–${timeOf(e.end)}`;
});

function close() {
  eventSheet.value = null;
}

/** Days between two YYYY-MM-DD strings. */
const daysBetween = (a: string, b: string) => Math.round((parseDay(b).getTime() - parseDay(a).getTime()) / 86_400_000);

async function save() {
  const patch: EventPatch = {};
  if (form.title.trim() && form.title.trim() !== e.title) patch.title = form.title.trim();
  if (e.all_day) {
    if (form.day !== startDay) patch.day = form.day;
  } else if (form.day !== startDay || form.start !== timeOf(e.start) || form.end !== timeOf(e.end)) {
    // A multi-day event keeps its span when its day changes.
    const newEndDay = addDays(e.end.slice(0, 10), daysBetween(startDay, form.day));
    const start = `${form.day}T${form.start}`;
    const end = `${newEndDay}T${form.end}`;
    if (end <= start) {
      showToast("The event has to end after it starts");
      return;
    }
    patch.start = start;
    patch.end = end;
  }
  if (!Object.keys(patch).length) return close();
  saving.value = true;
  const ok = await editEvent(e, patch);
  saving.value = false;
  if (ok) close();
}

async function remove() {
  if (await deleteEvent(e)) close();
}

/** Keep the length when the start moves, like Google Calendar does. */
function onStartChange(value: string) {
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
  const length = toMin(form.end) - toMin(form.start);
  form.start = value;
  if (length > 0 && value) {
    const end = Math.min(toMin(value) + length, 23 * 60 + 59);
    form.end = `${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`;
  }
}

const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && close();
let releaseBack = () => {};
onMounted(() => {
  releaseBack = useBackButton(close);
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  releaseBack();
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div class="backdrop" @click.self="close">
    <form class="sheet" @submit.prevent="save">
      <template v-if="event.editable">
        <input v-model="form.title" class="title-input event-title" maxlength="500" placeholder="Event title" />

        <div class="field row">
          <label class="half">
            <span class="label">Day</span>
            <input v-model="form.day" type="date" required />
          </label>
          <template v-if="!event.all_day">
            <label class="quarter">
              <span class="label">Starts</span>
              <input
                :value="form.start"
                type="time"
                required
                @change="onStartChange(($event.target as HTMLInputElement).value)"
              />
            </label>
            <label class="quarter">
              <span class="label">Ends</span>
              <input v-model="form.end" type="time" required />
            </label>
          </template>
        </div>

        <p v-if="event.recurring || event.has_guests" class="hint">
          <span v-if="event.recurring">↻ Changes apply to this occurrence only. </span>
          <span v-if="event.has_guests">Guests will get Google's update email.</span>
        </p>
      </template>

      <template v-else>
        <h3>{{ event.title }}</h3>
        <p class="hint">{{ when }}</p>
        <p class="hint">You're a guest — only the organizer can change this event.</p>
      </template>

      <div class="actions">
        <a v-if="event.link" class="secondary button-link" :href="event.link" target="_blank" rel="noopener">
          {{ event.link.includes("meet.google") || event.link.includes("zoom") ? "Join" : "Open" }}
        </a>
        <template v-if="event.editable">
          <button type="button" class="secondary danger" @click="remove">Delete</button>
          <button type="submit" class="primary" :disabled="saving">Save</button>
        </template>
        <button v-else type="button" class="primary" @click="close">Close</button>
      </div>
    </form>
  </div>
</template>
