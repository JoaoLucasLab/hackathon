import type { Day, Schedule, ScheduledClass } from "../api/schemas";
import { calendarEvents, untimedSections } from "./WeekCalendar";
import { formatTime } from "./ConstraintChips";
import { professorName } from "./ProfessorChip";
import type { ProfessorIndex } from "./ScheduleDetail";
import { BlockTag, DAYS, blockLabel, formatAsOf, sectionCode, timedMeetings } from "./scheduleFormat";

/** One calendar row is 15 minutes, drawn this many pixels tall. */
const SLOT_PX = 13;
const WEEKDAYS: Day[] = ["M", "T", "W", "R", "F"];

/** Per-course colors, in the order the classes are listed, so no two classes share one. */
const PALETTE = [
  "bg-sq-sage",
  "bg-sq-sky",
  "bg-sq-clay",
  "bg-sq-butter",
  "bg-sq-sea",
  "bg-sq-lilac",
  "bg-sq-stone",
];

export function courseColors(schedule: Schedule): Map<string, string> {
  const colors = new Map<string, string>();
  for (const c of schedule.classes) {
    if (!colors.has(c.section.course_code)) {
      colors.set(c.section.course_code, PALETTE[colors.size % PALETTE.length] ?? "bg-sq-stone");
    }
  }
  return colors;
}

function clock(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** "9:00–10:15 AM", or "11:30 AM–12:45 PM" when the half of the day changes. */
export function timeRange(start: string, end: string): string {
  const a = formatTime(start);
  const b = formatTime(end);
  return a.slice(-2) === b.slice(-2) ? `${a.slice(0, -3)}–${b}` : `${a}–${b}`;
}

const ABBR = Object.fromEntries(DAYS.map((d) => [d.day, d.abbr])) as Record<Day, string>;

/** "Mon to Thu" for a run of days, else "Mon, Wed, Fri". */
export function dayRange(days: Day[]): string {
  const order = DAYS.map((d) => d.day).filter((d) => days.includes(d));
  if (order.length === 0) return "";
  const idx = order.map((d) => DAYS.findIndex((x) => x.day === d));
  const run = idx.every((v, i) => i === 0 || v === (idx[i - 1] ?? 0) + 1);
  if (run && order.length > 2) return `${ABBR[order[0] as Day]} to ${ABBR[order[order.length - 1] as Day]}`;
  return order.map((d) => ABBR[d]).join(", ");
}

/** "Mon to Thu · 9:00 AM to 1:45 PM", or "Online, no set times". */
export function weekSpan(schedule: Schedule): string {
  const meetings = schedule.classes.flatMap((c) => timedMeetings(c.section));
  if (meetings.length === 0) return "Online, no set times";
  const days = [...new Set(meetings.flatMap((m) => m.days ?? []))];
  const starts = meetings.map((m) => m.start_time ?? "").sort();
  const ends = meetings.map((m) => m.end_time ?? "").sort();
  return `${dayRange(days)} · ${timeRange(starts[0] ?? "", ends[ends.length - 1] ?? "")}`;
}

/** "Mon, Wed 9:00 to 10:00 AM" for the list; online classes say so. */
function meetingLine(item: ScheduledClass): string {
  const meetings = timedMeetings(item.section);
  if (meetings.length === 0) {
    return item.section.delivery_method === "online" ? "Online, no set time" : "Time to be announced";
  }
  return meetings
    .map((m) => `${(m.days ?? []).map((d) => ABBR[d]).join(", ")} ${timeRange(m.start_time ?? "", m.end_time ?? "")}`)
    .join("; ");
}

function SeatsPill({ item }: { item: ScheduledClass }) {
  const { open } = item.section.seats;
  if (item.waitlisted) {
    return <span className="whitespace-nowrap rounded-full bg-warn-tint px-2 py-0.5 text-xs text-warn">Waitlist</span>;
  }
  return (
    <span className="whitespace-nowrap rounded-full bg-ok-tint px-2 py-0.5 text-xs tabular-nums text-ok">
      {open} {open === 1 ? "seat" : "seats"} open
    </span>
  );
}

interface WeekGlanceProps {
  schedule: Schedule;
  /** Requirement names by id, for the small label next to each course. */
  reqNames: Map<string, string>;
  /** Professors by id, to name each section's professor. Left out: no professor line. */
  professors?: ProfessorIndex;
}

/** "Taught by Ana Lopez", from the section's instructor ids and the professor list. */
function professorLine(item: ScheduledClass, professors: ProfessorIndex): string {
  if (professors === null) return "";
  const names = (item.section.instructor_ids ?? [])
    .map((id) => professors.get(id))
    .filter((p) => p !== undefined)
    .map(professorName);
  return names.length > 0 ? `Taught by ${names.join(", ")}` : "Professor not listed yet";
}

/**
 * A compact week for the chat card: a small Mon to Fri calendar (days with no class
 * are marked "Free") beside a list of the classes with their times and seats. Every
 * block carries its course code, so color is never the only signal.
 */
export function WeekGlance({ schedule, reqNames, professors }: WeekGlanceProps) {
  const colors = courseColors(schedule);
  const events = calendarEvents(schedule);
  const days = events.some((e) => e.day === "S") ? [...WEEKDAYS, "S" as Day] : WEEKDAYS;
  const from = events.length ? Math.floor(Math.min(...events.map((e) => e.start)) / 60) * 60 : 9 * 60;
  const to = events.length
    ? Math.max(Math.ceil(Math.max(...events.map((e) => e.end)) / 60) * 60, from + 60)
    : from + 4 * 60;
  const rows = (to - from) / 15;
  const hours = Array.from({ length: (to - from) / 60 + 1 }, (_, i) => from + i * 60);
  const untimed = untimedSections(schedule);
  const asOf = schedule.classes.map((c) => c.section.seats.as_of).sort()[0];

  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-2">
        <div
          role="group"
          aria-label="Week at a glance"
          className="grid gap-x-1"
          style={{ gridTemplateColumns: `34px repeat(${days.length}, minmax(0, 1fr))` }}
        >
          <div aria-hidden="true" />
          {days.map((d) => (
            <div key={d} aria-hidden="true" className="pb-1 text-center text-[11px] text-muted">
              {ABBR[d]}
            </div>
          ))}
          <div
            aria-hidden="true"
            className="relative text-right text-[10px] tabular-nums text-muted"
            style={{ height: rows * SLOT_PX }}
          >
            {hours.map((h) => (
              <span
                key={h}
                className="absolute right-1.5 -translate-y-1/2"
                style={{ top: ((h - from) / 15) * SLOT_PX }}
              >
                {formatTime(clock(h)).replace(/:00 (AM|PM)$/, ":00")}
              </span>
            ))}
          </div>
          {days.map((d) => {
            const today = events.filter((e) => e.day === d);
            const free = today.length === 0;
            return (
              <section
                key={d}
                aria-label={`${DAYS.find((x) => x.day === d)?.name ?? d}${free ? ": free" : ""}`}
                className={`relative rounded-md ${free ? "glance-free" : "bg-paper"}`}
                style={{ height: rows * SLOT_PX }}
              >
                {free ? (
                  <span className="absolute inset-0 grid place-items-center text-[11px] text-muted">Free</span>
                ) : (
                  <ul>
                    {today.map((e) => {
                      const swatch = e.block === "First Block" ? "sw-first" : e.block === "Second Block" ? "sw-second" : "";
                      const width = 100 / e.lanes;
                      return (
                        <li
                          key={e.key}
                          data-testid="calendar-event"
                          aria-label={`${e.section.course_code}, ${timeRange(clock(e.start), clock(e.end))}${e.block ? `, ${e.block}` : ""}`}
                          className={`absolute overflow-hidden rounded-[4px] border border-[rgba(26,26,26,0.14)] px-1 pt-0.5 text-[10px] font-semibold leading-tight text-ink ${colors.get(e.section.course_code) ?? "bg-sq-stone"}`}
                          style={{
                            top: ((e.start - from) / 15) * SLOT_PX,
                            height: Math.max(((e.end - e.start) / 15) * SLOT_PX - 2, 12),
                            left: `calc(${e.lane * width}% + 1px)`,
                            width: `calc(${width}% - 2px)`,
                          }}
                        >
                          {swatch && <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-1 ${swatch}`} />}
                          <span aria-hidden="true" className={swatch ? "mt-1 block" : "block"}>
                            {e.section.course_code}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
        {untimed.length > 0 && (
          <p className="text-[12px] text-muted">
            Online, no set time: {untimed.map((s) => s.course_code).join(", ")}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        {asOf && <p className="text-[12px] text-muted">Seats as of {formatAsOf(asOf)}</p>}
        <ul aria-label="Classes at a glance" className="flex flex-col">
          {schedule.classes.map((c) => {
            const fills = (c.requirement_ids ?? []).map((id) => reqNames.get(id)).filter(Boolean);
            const block = blockLabel(c.section);
            return (
              <li key={c.section.id} className="flex items-start gap-2.5 border-b border-line-soft py-[7px] last:border-b-0">
                <span
                  aria-hidden="true"
                  className={`mt-1 size-3 shrink-0 rounded-[3px] ${colors.get(c.section.course_code) ?? "bg-sq-stone"}`}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  {/* One line: the code, then the requirement it fills (cut short if long). */}
                  <p className="truncate text-sm" title={fills.join(", ") || undefined}>
                    <span className="font-semibold">{sectionCode(c.section)}</span>
                    {fills.length > 0 && <span className="text-[12px] text-muted"> {fills.join(", ")}</span>}
                  </p>
                  <p className="text-[12px] tabular-nums text-muted">{meetingLine(c)}</p>
                  {professors !== undefined && professorLine(c, professors) && (
                    <p className="text-[12px] text-ink">{professorLine(c, professors)}</p>
                  )}
                  {block && (
                    <span className="self-start">
                      <BlockTag label={block} />
                    </span>
                  )}
                </div>
                <SeatsPill item={c} />
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
