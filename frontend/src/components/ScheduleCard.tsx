import { ChevronRight } from "lucide-react";
import type { Schedule } from "../api/schemas";
import { formatTime } from "./ConstraintChips";
import { BlockTag, DAYS, blockLabel, plural, timedMeetings, whenLine } from "./scheduleFormat";
import { Button } from "./ui/Button";
import { TagSquare } from "./ui/TagSquare";

function latestEnd(s: Schedule): string | null {
  const ends = s.classes.flatMap((c) => timedMeetings(c.section).map((m) => m.end_time ?? ""));
  return ends.length ? (ends.sort().at(-1) ?? null) : null;
}

function WeekDots({ schedule }: { schedule: Schedule }) {
  const used = new Set(
    schedule.classes.flatMap((c) => timedMeetings(c.section).flatMap((m) => m.days ?? [])),
  );
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

interface ScheduleCardProps {
  schedule: Schedule;
  /** Opens the full schedule: calendar, reasons, professors, backups. */
  onSelect?: (schedule: Schedule) => void;
}

/** One schedule option as a slip: summary above the perforation, classes below. */
export function ScheduleCard({ schedule, onSelect }: ScheduleCardProps) {
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
          {onSelect && <Button variant="text" onClick={() => onSelect(schedule)} aria-label={`See details for option ${schedule.rank}`}><ChevronRight size={20} aria-hidden="true" /></Button>}
        </div>
        <div className="slip-perf" />
        <div className="flex items-center justify-between gap-4 px-6 py-4"><WeekDots schedule={schedule} /><span className="text-[13px] text-muted">{plural(schedule.classes.length, "class")}</span></div>
        <details className="px-6 pb-3"><summary className="min-h-11 cursor-pointer py-3 text-sm text-muted">Preview classes</summary>
        <ul className="flex flex-col py-2">
          {schedule.classes.map((c) => {
            const block = blockLabel(c.section);
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
                    <p className="text-sm tabular-nums text-muted">{whenLine(c.section)}</p>
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
        </details>
      </div>
    </article>
  );
}
