import { useId, useState } from "react";

import type { Schedule } from "../api/schemas";
import { ClassRow, Warning, useClassRowData } from "./ScheduleDetail";
import { WeekCalendar } from "./WeekCalendar";
import { DAYS, formatAsOf, plural, timedMeetings } from "./scheduleFormat";
import { Icon } from "./ui/Icon";

const ADVISING = "Confirm with BYU-Idaho Academic Advising.";

/** "MWF", from the days the classes meet. "online only" when none has a set time. */
export function dayLetters(schedule: Schedule): string {
  const used = new Set(
    schedule.classes.flatMap((c) => timedMeetings(c.section).flatMap((m) => m.days ?? [])),
  );
  const letters = DAYS.filter((d) => used.has(d.day))
    .map((d) => d.day)
    .join("");
  return letters || "online only";
}

/** "Option 1: 13 credits, MWF, not chosen": the line an older card collapses to. */
export function summaryLine(schedule: Schedule, option: number, confirmed: boolean): string {
  return `Option ${option}: ${plural(schedule.total_credits, "credit")}, ${dayLetters(schedule)}, ${
    confirmed ? "confirmed" : "not chosen"
  }`;
}

/** The oldest seat count in the schedule: "Seats as of Nov 13, 3:00 PM." */
function seatsAsOf(schedule: Schedule): string | null {
  const times = schedule.classes.map((c) => c.section.seats.as_of).sort();
  return times[0] ? `Seats as of ${formatAsOf(times[0])}.` : null;
}

/** A text label, not color alone. */
function ConfirmedLabel() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ink px-2 py-0.5 text-xs text-surface">
      <Icon name="check" size={12} />
      Confirmed
    </span>
  );
}

interface ChatScheduleCardProps {
  schedule: Schedule;
  option: number;
  /** This is the student's confirmed plan. */
  confirmed: boolean;
  /** Older cards start collapsed to one line; the latest starts open. */
  defaultOpen: boolean;
}

/**
 * AI-08: the one schedule an assistant message shows, rendered only from the
 * `build_schedules` tool result: week calendar, each class with the requirement
 * it fills, professors (star and RMP link), backups, seats and warnings.
 */
export function ChatScheduleCard({ schedule, option, confirmed, defaultOpen }: ChatScheduleCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const { byId, reqNames, professorsFailed } = useClassRowData();
  const bodyId = useId();
  const titleId = useId();
  const seats = seatsAsOf(schedule);

  if (!open) {
    return (
      <article aria-labelledby={titleId} className="rounded-card border border-line bg-surface">
        <button
          type="button"
          aria-expanded={false}
          aria-controls={bodyId}
          onClick={() => setOpen(true)}
          className="flex min-h-11 w-full items-center justify-between gap-3 rounded-card px-4 py-2 text-left text-sm hover:bg-field"
        >
          <span id={titleId} className="tabular-nums">
            {summaryLine(schedule, option, confirmed)}
          </span>
          <span className="flex shrink-0 items-center gap-2">
            {confirmed && <ConfirmedLabel />}
            <Icon name="chevronDown" size={16} />
            <span className="sr-only">Show option {option}</span>
          </span>
        </button>
        <div id={bodyId} hidden />
      </article>
    );
  }

  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4 md:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 id={titleId} className="font-serif text-[26px] font-normal leading-none">
              Option {option}
            </h2>
            {confirmed && <ConfirmedLabel />}
          </div>
          <p className="text-sm tabular-nums text-muted">
            {plural(schedule.total_credits, "credit")}, {plural(schedule.classes.length, "class")},{" "}
            {dayLetters(schedule)}
          </p>
        </div>
        <button
          type="button"
          aria-expanded={true}
          aria-controls={bodyId}
          onClick={() => setOpen(false)}
          className="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-btn px-2 text-sm text-muted hover:text-ink"
        >
          Collapse
          <Icon name="chevronDown" size={16} className="rotate-180" />
        </button>
      </div>

      <div id={bodyId} className="flex flex-col gap-4">
        {(schedule.warnings ?? []).map((w, i) => (
          <Warning key={i} message={w.message} />
        ))}
        <WeekCalendar schedule={schedule} />
        <ul aria-label={`Classes in option ${option}`} className="rounded-card border border-line px-4">
          {schedule.classes.map((c) => (
            <ClassRow
              key={c.section.id}
              item={c}
              byId={byId}
              fills={(c.requirement_ids ?? []).map((id) => reqNames.get(id) ?? id)}
            />
          ))}
        </ul>
        {professorsFailed && (
          <p className="text-sm text-muted">Professor details couldn't load. Try again later.</p>
        )}
        <p className="text-[13px] text-muted">
          {seats && <>{seats} </>}
          <span className="font-medium text-ink">{schedule.advising_note ?? ADVISING}</span>
        </p>
      </div>
    </article>
  );
}
