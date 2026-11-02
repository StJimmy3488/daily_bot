export interface Task {
  id: number;
  title: string;
  notes: string | null;
  status: "todo" | "done" | "dropped";
  priority: 1 | 2 | 3;
  due_date: string | null; // YYYY-MM-DD
  due_time: string | null; // HH:MM
  est_minutes: number | null;
  recurrence_rule: string | null;
  repeat_label: string | null;
}

export interface CalendarEvent {
  id: number;
  title: string;
  start: string; // local YYYY-MM-DDTHH:MM
  end: string;
  all_day: boolean;
  link: string | null;
  editable: boolean; // false when you're only a guest
  recurring: boolean; // changes apply to this occurrence only
  has_guests: boolean; // guests get Google's update email
}

export interface EventPatch {
  title?: string;
  start?: string; // local YYYY-MM-DDTHH:MM
  end?: string;
  day?: string; // all-day events
}

export interface Day {
  date: string;
  tasks: Task[];
  events: CalendarEvent[];
}

export interface DayView extends Day {
  overdue: Task[];
}

export interface Week {
  start: string;
  days: Day[];
}

export interface Meta {
  today: string;
  timezone: string;
  work_hours: [string, string];
  ai: boolean;
  calendar: boolean;
}

export interface Closed {
  task: Task;
  next: Task | null;
}

export interface PlanBlock {
  start: string;
  end: string;
  title: string;
  task_id: number | null;
  fixed: boolean;
}

export interface Plan {
  date: string;
  blocks: PlanBlock[];
  unplaced: Task[];
  note: string;
}

export type TaskInput = Partial<
  Pick<Task, "title" | "notes" | "priority" | "due_date" | "due_time" | "est_minutes" | "recurrence_rule">
>;
