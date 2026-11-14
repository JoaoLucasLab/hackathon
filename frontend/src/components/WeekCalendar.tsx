import type { Day, Schedule, Section } from "../api/schemas";
import { formatTime } from "./ConstraintChips";
import { DAYS, blockLabel, sectionCode, timedMeetings, type BlockLabel } from "./scheduleFormat";
import { TagSquare } from "./ui/TagSquare";

/** One calendar row is 15 minutes. */
const SLOT = 15;
const ROW_PX = 18;

export function minutesOf(time: string): number {
  const [h = 0, m = 0] = time.split(":").map(Number);
  return h * 60 + m;
}

export interface CalendarEvent {
  key: string;
  section: Section;
  day: Day;
  start: number;
  end: number;
  block: BlockLabel | null;
  /** Side-by-side lane, for classes that overlap in time (First vs Second Block). */
  lane: number;
  lanes: number;
}

/** Every timed meeting of every class, one event per weekday it meets. */
export function calendarEvents(schedule: Schedule): CalendarEvent[] {
  const events: CalendarEvent[] = [];
  for (const c of schedule.classes) {
    timedMeetings(c.section).forEach((m, i) => {
      for (const day of m.days ?? []) {
        events.push({
          key: `${c.section.id}|${i}|${day}`,
          section: c.section,
          day,
          start: minutesOf(m.start_time ?? ""),
          end: minutesOf(m.end_time ?? ""),
          block: blockLabel(c.section),
          lane: 0,
          lanes: 1,
        });
      }
    });
  }
  // Overlapping events on the same day share the column in lanes, so both stay readable.
  for (const { day } of DAYS) {
    const today = events.filter((e) => e.day === day).sort((a, b) => a.start - b.start);
    let group: CalendarEvent[] = [];
    let groupEnd = -1;
    const close = () => {
      const laneEnds: number[] = [];
      for (const e of group) {
        let lane = laneEnds.findIndex((end) => end <= e.start);
        if (lane === -1) lane = laneEnds.length;
        laneEnds[lane] = e.end;
        e.lane = lane;
      }
      for (const e of group) e.lanes = laneEnds.length;
    };
    for (const e of today) {
      if (e.start >= groupEnd && group.length) {
        close();
        group = [];
      }
      group.push(e);
      groupEnd = Math.max(groupEnd, e.end);
    }
    if (group.length) close();
  }
  return events;
}

/** Sections with no set meeting time (online), listed under the calendar. */
export function untimedSections(schedule: Schedule): Section[] {
  return schedule.classes.map((c) => c.section).filter((s) => timedMeetings(s).length === 0);
}

function span(events: CalendarEvent[]): { from: number; to: number } {
  if (events.length === 0) return { from: 8 * 60, to: 17 * 60 };
  const from = Math.floor(Math.min(...events.map((e) => e.start)) / 60) * 60;
  const to = Math.ceil(Math.max(...events.map((e) => e.end)) / 60) * 60;
  return { from, to: Math.max(to, from + 60) };
}

/** Grid row line for a time, counted from the top of the calendar (row 1). */
export function rowLine(minutes: number, from: number): number {
  return Math.round((minutes - from) / SLOT) + 1;
}

const STYLE: Record<"full" | BlockLabel, string> = {
  full: "bg-ink text-surface border-ink",
  "First Block": "bg-surface text-ink border-ink",
  "Second Block": "bg-surface text-ink border-ink",
};

function clock(minutes: number): string {
  return formatTime(`${Math.floor(minutes / 60)}:${minutes % 60}`);
}

function EventBox({ event, from }: { event: CalendarEvent; from: number }) {
  const when = `${clock(event.start)} to ${clock(event.end)}`;
  const label = [sectionCode(event.section), when, event.block].filter(Boolean).join(", ");
  const swatch =
    event.block === "First Block" ? "sw-first" : event.block === "Second Block" ? "sw-second" : "";
  return (
    <li
      aria-label={label}
      data-testid="calendar-event"
      className={`relative m-px flex min-w-0 flex-col overflow-hidden break-words rounded-md border px-1 py-1 text-[11px] leading-tight sm:px-1.5 sm:text-[12px] ${STYLE[event.block ?? "full"]}`}
      style={{
        gridRow: `${rowLine(event.start, from)} / ${rowLine(event.end, from)}`,
        gridColumn: `${event.lane + 1} / span 1`,
      }}
    >
      {swatch && <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-1.5 ${swatch}`} />}
      <span aria-hidden="true" className={`font-semibold ${swatch ? "mt-1.5" : ""}`}>
        {event.section.course_code}
      </span>
      {event.block && (
        <span aria-hidden="true">
          {event.block}
        </span>
      )}
    </li>
  );
}

/** Monday to Saturday week view of one schedule. Scrolls sideways inside its own box. */
export function WeekCalendar({ schedule }: { schedule: Schedule }) {
  const events = calendarEvents(schedule);
  const { from, to } = span(events);
  const rows = (to - from) / SLOT;
  const hours = Array.from({ length: (to - from) / 60 }, (_, i) => from + i * 60);
  const untimed = untimedSections(schedule);

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <div className="grid min-w-[760px] grid-cols-[56px_repeat(6,minmax(0,1fr))] p-3">
          <div aria-hidden="true" />
          {DAYS.map((d) => (
            <div key={d.day} aria-hidden="true" className="pb-2 text-center text-sm font-semibold">
              {d.abbr}
            </div>
          ))}
          <div
            aria-hidden="true"
            className="grid text-right text-[11px] tabular-nums text-muted"
            style={{ gridTemplateRows: `repeat(${rows}, ${ROW_PX}px)` }}
          >
            {hours.map((h) => (
              <span key={h} className="pr-2" style={{ gridRow: `${rowLine(h, from)} / span 4` }}>
                {clock(h)}
              </span>
            ))}
          </div>
          {DAYS.map((d) => {
            const today = events.filter((e) => e.day === d.day);
            const lanes = Math.max(1, ...today.map((e) => e.lanes));
            return (
              <section
                key={d.day}
                aria-label={d.name}
                className="border-l border-line-soft"
                style={{
                  backgroundImage: `repeating-linear-gradient(to bottom, var(--line-soft) 0 1px, transparent 1px ${ROW_PX * 4}px)`,
                }}
              >
                <ul
                  className="grid"
                  style={{
                    gridTemplateRows: `repeat(${rows}, ${ROW_PX}px)`,
                    gridTemplateColumns: `repeat(${lanes}, minmax(0, 1fr))`,
                  }}
                >
                  {today.map((e) => (
                    <EventBox key={e.key} event={e} from={from} />
                  ))}
                </ul>
                {today.length === 0 && <span className="sr-only">No class</span>}
              </section>
            );
          })}
        </div>
      </div>
      {untimed.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold">Online, no set time</h3>
          <ul aria-label="Online, no set time" className="flex flex-col gap-1">
            {untimed.map((s) => (
              <li key={s.id} className="flex items-center gap-2 text-sm">
                <TagSquare courseCode={s.course_code} />
                <span className="font-semibold">{sectionCode(s)}</span>
                <span className="text-muted">
                  {s.title}
                  {s.delivery_method === "online" ? "" : ", time to be announced"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
