import type { Day, Meeting, Section } from "../api/schemas";
import { formatTime } from "./ConstraintChips";

export const DAYS: { day: Day; short: string; abbr: string; name: string }[] = [
  { day: "M", short: "M", abbr: "Mon", name: "Monday" },
  { day: "T", short: "T", abbr: "Tue", name: "Tuesday" },
  { day: "W", short: "W", abbr: "Wed", name: "Wednesday" },
  { day: "R", short: "R", abbr: "Thu", name: "Thursday" },
  { day: "F", short: "F", abbr: "Fri", name: "Friday" },
  { day: "S", short: "S", abbr: "Sat", name: "Saturday" },
];

const DAY_ABBR = Object.fromEntries(DAYS.map((d) => [d.day, d.abbr])) as Record<Day, string>;

export function plural(n: number, word: string): string {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

export function timedMeetings(section: Section): Meeting[] {
  return (section.meetings ?? []).filter((m) => !m.tba && m.start_time && m.end_time);
}

/** "Mon, Wed 10:15 AM to 11:45 AM, STC 231" (frontend.md class row). */
export function whenLine(section: Section): string {
  const meetings = timedMeetings(section);
  if (meetings.length === 0) {
    return section.delivery_method === "online" ? "Online, no set time" : "Time to be announced";
  }
  return meetings
    .map((m) => {
      const days = (m.days ?? []).map((d) => DAY_ABBR[d]).join(", ");
      const time = `${formatTime(m.start_time ?? "")} to ${formatTime(m.end_time ?? "")}`;
      return [`${days} ${time}`, m.room].filter(Boolean).join(", ");
    })
    .join("; ");
}

export type BlockLabel = "First Block" | "Second Block";

export function blockLabel(section: Section): BlockLabel | null {
  if (section.block === "first") return "First Block";
  if (section.block === "second") return "Second Block";
  return null;
}

/** Text label plus a pattern swatch: never color alone (AGENTS.md). */
export function BlockTag({ label }: { label: BlockLabel }) {
  const swatch = label === "First Block" ? "sw-first" : "sw-second";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-tag bg-field px-2 py-0.5 text-[13px]">
      <span aria-hidden="true" className={`h-2.5 w-3 rounded-[2px] ${swatch}`} />
      {label}
    </span>
  );
}

export function sectionCode(section: Section): string {
  return `${section.course_code}-${section.section}`;
}

/** "Nov 13, 3:00 PM" */
export function formatAsOf(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Seats are always shown as "seats as of <time>" and never promised. */
export function seatsLine(section: Section, waitlisted = false): string {
  const when = formatAsOf(section.seats.as_of);
  if (waitlisted) return `Waitlist. Seats as of ${when}: ${section.seats.open} open.`;
  return `Seats as of ${when}: ${section.seats.open} of ${section.seats.total} open.`;
}

export const CHECK_PREFIX = "Check this before registering";

export function warningText(message: string): string {
  return message.startsWith(CHECK_PREFIX) ? message : `${CHECK_PREFIX}: ${message}`;
}
