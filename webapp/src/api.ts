import { initData } from "./telegram";
import type { CalendarEvent, Closed, DayView, EventPatch, Meta, Plan, Task, TaskInput, Week } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      Authorization: `tma ${initData}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : "Please check the fields";
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const q = (params: Record<string, string | undefined>) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return s ? `?${s}` : "";
};

export const api = {
  meta: () => request<Meta>("GET", "/meta"),
  day: (day?: string) => request<DayView>("GET", `/day${q({ day })}`),
  week: (start?: string) => request<Week>("GET", `/week${q({ start })}`),
  inbox: () => request<Task[]>("GET", "/inbox"),
  create: (input: TaskInput) => request<Task>("POST", "/tasks", input),
  update: (id: number, patch: TaskInput) => request<Task>("PATCH", `/tasks/${id}`, patch),
  complete: (id: number) => request<Closed>("POST", `/tasks/${id}/complete`),
  drop: (id: number) => request<Closed>("POST", `/tasks/${id}/drop`),
  reopen: (id: number) => request<Task>("POST", `/tasks/${id}/reopen`),
  plan: (day?: string) => request<Plan>("POST", `/plan${q({ day })}`),
  applyPlan: (date: string, items: { task_id: number; time: string }[]) =>
    request<Task[]>("POST", "/plan/apply", { date, items }),
  updateEvent: (id: number, patch: EventPatch) => request<CalendarEvent>("PATCH", `/events/${id}`, patch),
  deleteEvent: (id: number) => request<void>("DELETE", `/events/${id}`),
};
