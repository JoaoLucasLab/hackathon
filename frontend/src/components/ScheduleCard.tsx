import type { Day, Meeting, Schedule, ScheduledClass } from "../api/schemas";
import { formatTime } from "./ConstraintChips";
import { TagSquare } from "./ui/TagSquare";

const DAYS: { day: Day; short: string; name: string }[] = [
  { day: "M", short: "M", name: "Monday" },
  { day: "T", short: "T", name: "Tuesday" },
  { day: "W", short: "W", name: "Wednesday" },
  { day: "R", short: "R", name: "Thursday" },
  { day: "F", short: "F", name: "Friday" },
  { day: "S", short: "S", name: "Saturday" },
];

const DAY_ABBR: Record<Day, string> = { M: "Mon", T: "Tue", W: "Wed", R: "Thu", F: "Fri", S: "Sat" };

function plural(n: number, word: string): string {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

function timedMeetings(c: ScheduledClass): Meeting[] {
  return (c.section.meetings ?? []).filter((m) => !m.tba && m.start_time && m.end_time);
}

/** "Mon, Wed 10:15 AM to 11:45 AM, STC 231" (frontend.md class row). */
function whenLine(c: ScheduledClass): string {
  const meetings = timedMeetings(c);
  if (meetings.length === 0) {
    return c.section.delivery_method === "online" ? "Online, no set time" : "Time to be announced";
  }
  return meetings
    .map((m) => {
      const days = (m.days ?? []).map((d) => DAY_ABBR[d]).join(", ");
      const time = `${formatTime(m.start_time ?? "")} to ${formatTime(m.end_time ?? "")}`;
      return [`${days} ${time}`, m.room].filter(Boolean).join(", ");
    })
    .join("; ");
}

function blockLabel(c: ScheduledClass): string | null {
  if (c.section.block === "first") return "First Block";
  if (c.section.block === "second") return "Second Block";
  return null;
}

function BlockTag({ label }: { label: string }) {
  const swatch = label === "First Block" ? "sw-first" : "sw-second";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-tag bg-field px-2 py-0.5 text-[13px]">
      <span aria-hidden="true" className={`h-2.5 w-3 rounded-[2px] ${swatch}`} />
      {label}
    </span>
  );
}

function latestEnd(s: Schedule): string | null {
  const ends = s.classes.flatMap((c) => timedMeetings(c).map((m) => m.end_time ?? ""));
  return ends.length ? ends.sort().at(-1) ?? null : null;
}

function WeekDots({ schedule }: { schedule: Schedule }) {
  const used = new Set(schedule.classes.flatMap((c) => timedMeetings(c).flatMap((m) => m.days ?? [])));
  return (
    <ul aria-label="Class days" className="flex gap-2.5">
      {DAYS.map(({ day, short, name }) => {
        const has = used.has(day);
        return (
          <li key={day} className="flex flex-col items-center gap-1">
            <span
              aria-hidden="true"
              className={`size-[18px] rounded-full ${has ? "bg-ink" : "border-[1.5px] border-[#D3CEC3]"}`}
            />
            <span aria-hidden="true" className={`text-xs ${has ? "text-ink" : "text-muted"}`}>
              {short}
            </span>
            <span className="sr-only">
              {name}: {has ? "class" : "no class"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** One schedule option as a slip: summary above the perforation, classes below. */
export function ScheduleCard({ schedule }: { schedule: Schedule }) {
  const end = latestEnd(schedule);
  const titleId = `schedule-${schedule.id}`;
  return (
    <article aria-labelledby={titleId} className="slip-wrap">
      <div className="slip flex flex-col">
        <div className="flex h-[96px] items-center justify-between gap-4 px-6">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="flex items-center gap-2.5">
              <h2 id={titleId} className="font-serif text-[28px] font-normal leading-none">
                Option {schedule.rank}
              </h2>
              {schedule.rank === 1 && (
                <span className="rounded-full bg-ink px-2 py-0.5 text-xs text-surface">Best fit</span>
              )}
            </div>
            <p className="text-sm tabular-nums text-muted">
              {plural(schedule.total_credits, "credit")}
              {end ? `, done by ${formatTime(end)}` : ""}
            </p>
          </div>
          <WeekDots schedule={schedule} />
        </div>
        <div className="slip-perf" />
        <ul className="flex flex-col px-6 py-2">
          {schedule.classes.map((c) => {
            const block = blockLabel(c);
            return (
              <li
                key={c.section.id}
                className="flex items-start justify-between gap-4 border-b border-line-soft py-3 last:border-b-0"
              >
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-1.5">
                    <TagSquare courseCode={c.section.course_code} size={14} />
                  </span>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <p>
                      <span className="font-semibold">
                        {c.section.course_code}-{c.section.section}
                      </span>
                      <span className="text-muted"> {c.section.title}</span>
                    </p>
                    <p className="text-sm tabular-nums text-muted">{whenLine(c)}</p>
                    {block && (
                      <span className="mt-1">
                        <BlockTag label={block} />
                      </span>
                    )}
                  </div>
                </div>
                <p className="shrink-0 text-sm tabular-nums text-muted">
                  {plural(c.section.credits, "credit")}
                </p>
              </li>
            );
          })}
        </ul>
      </div>
    </article>
  );
}
