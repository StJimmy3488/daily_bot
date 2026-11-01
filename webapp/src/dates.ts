// Dates travel as local "YYYY-MM-DD" strings; never through Date's UTC parsing.

export function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(day: string, n: number): string {
  const d = parseDay(day);
  d.setDate(d.getDate() + n);
  return formatDay(d);
}

export function weekdayIndex(day: string): number {
  return (parseDay(day).getDay() + 6) % 7; // Monday = 0
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Today", "Tomorrow", "Yesterday" or "Wed 4 Nov". */
export function dayLabel(day: string, today: string): string {
  if (day === today) return "Today";
  if (day === addDays(today, 1)) return "Tomorrow";
  if (day === addDays(today, -1)) return "Yesterday";
  return shortDay(day);
}

export function shortDay(day: string): string {
  const d = parseDay(day);
  return `${WEEKDAYS[weekdayIndex(day)]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function timeOf(local: string): string {
  return local.slice(11, 16); // "YYYY-MM-DDTHH:MM" -> "HH:MM"
}
