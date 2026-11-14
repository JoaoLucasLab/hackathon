import { useId, useState, type ReactNode } from "react";

import type { Schedule } from "../api/schemas";
import { TERM_LABEL } from "../config";
import { ClassRow, useClassRowData } from "./ScheduleDetail";
import { WeekGlance, courseColors, weekSpan } from "./WeekGlance";
import { CHECK_PREFIX, DAYS, plural, timedMeetings } from "./scheduleFormat";
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

/** Facts for the footer, from the schedule only. A check shows only when it is true. */
export function scheduleChecks(schedule: Schedule): { ok: boolean; text: string }[] {
  const warnings = [...(schedule.warnings ?? []), ...schedule.classes.flatMap((c) => c.warnings ?? [])];
  const prereqs = new Set(
    warnings
      .filter((w) => w.kind === "prerequisite_check" || w.kind === "unparsed_prereq")
      .map((w) => w.course_code ?? w.message),
  ).size;
  const waitlisted = schedule.classes.filter((c) => c.waitlisted).length;
  return [
    prereqs === 0
      ? { ok: true, text: "Prerequisites met" }
      : { ok: false, text: `${plural(prereqs, "prerequisite")} to check` },
    waitlisted === 0
      ? { ok: true, text: "Open seats" }
      : { ok: false, text: `${waitlisted} ${waitlisted === 1 ? "class" : "classes"} on a waitlist` },
    // The solver never returns two classes that meet at the same time.
    { ok: true, text: "No conflicts" },
  ];
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
  /** "This works" / "Change something", shown in the footer of the card being asked about. */
  actions?: ReactNode;
}

/**
 * AI-08: the one schedule an assistant message shows, rendered only from the
 * `build_schedules` tool result. A week at a glance (small calendar and the class
 * list with seats), the checks, and the full class details (requirement each class
 * fills, professors, backups, warnings) behind "Class details".
 */
export function ChatScheduleCard({
  schedule,
  option,
  confirmed,
  defaultOpen,
  actions,
}: ChatScheduleCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [details, setDetails] = useState(false);
  const { byId, reqNames, professorsFailed } = useClassRowData();
  const bodyId = useId();
  const titleId = useId();
  const detailsId = useId();

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
    <article
      aria-labelledby={titleId}
      className="flex flex-col overflow-hidden rounded-card border border-line bg-surface shadow-[0_1px_2px_rgb(60_50_30/0.05)]"
    >
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-3 md:px-5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h2 id={titleId} className="text-[15px] font-semibold">
            Option {option}
          </h2>
          <span className="text-[15px] tabular-nums">
            · {TERM_LABEL} · {plural(schedule.total_credits, "credit")}
          </span>
          {confirmed && <ConfirmedLabel />}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[13px] tabular-nums text-muted">{weekSpan(schedule)}</span>
          <button
            type="button"
            aria-expanded={true}
            aria-controls={bodyId}
            onClick={() => setOpen(false)}
            className="grid size-11 place-items-center rounded-btn text-muted hover:bg-field hover:text-ink"
          >
            <Icon name="chevronDown" size={16} className="rotate-180" />
            <span className="sr-only">Collapse option {option}</span>
          </button>
        </div>
      </header>

      <div id={bodyId} className="flex flex-col gap-4 px-4 py-4 md:px-5">
        <WeekGlance schedule={schedule} reqNames={reqNames} professors={byId} />

        {(schedule.warnings ?? []).length > 0 && (
          <section
            aria-label={CHECK_PREFIX}
            className="flex flex-col gap-1 rounded-tag bg-warn-tint px-3 py-2 text-[12px] text-warn"
          >
            <h3 className="flex items-center gap-1.5 font-semibold">
              <Icon name="alert" size={13} />
              {CHECK_PREFIX}
            </h3>
            <ul className="flex list-disc flex-col gap-0.5 pl-8">
              {(schedule.warnings ?? []).map((w, i) => (
                <li key={i}>{w.message.replace(new RegExp(`^${CHECK_PREFIX}:?\\s*`), "")}</li>
              ))}
            </ul>
          </section>
        )}

        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={details}
            aria-controls={detailsId}
            onClick={() => setDetails((d) => !d)}
            className="inline-flex min-h-11 items-center gap-1 self-start text-sm font-medium text-muted hover:text-ink"
          >
            {details ? "Hide class details" : "Class details"}
            <Icon
              name="chevronDown"
              size={16}
              className={`transition-transform duration-150 ${details ? "rotate-180" : ""}`}
            />
          </button>
          <div id={detailsId} hidden={!details}>
            {details && (
              <>
                <ul aria-label={`Classes in option ${option}`} className="rounded-card border border-line px-4">
                  {schedule.classes.map((c) => (
                    <ClassRow
                      key={c.section.id}
                      item={c}
                      byId={byId}
                      fills={(c.requirement_ids ?? []).map((id) => reqNames.get(id) ?? id)}
                      color={courseColors(schedule).get(c.section.course_code)}
                    />
                  ))}
                </ul>
                {professorsFailed && (
                  <p className="mt-2 text-sm text-muted">Professor details couldn't load. Try again later.</p>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      <footer className="flex flex-col gap-3 border-t border-line-soft bg-paper px-4 py-3 sm:flex-row sm:items-center sm:justify-between md:px-5">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <ul aria-label="Checks" className="flex flex-wrap gap-x-3 gap-y-1 text-[13px]">
            {scheduleChecks(schedule).map((c) => (
              <li key={c.text} className={`flex items-center gap-1 ${c.ok ? "text-ok" : "text-warn"}`}>
                <Icon name={c.ok ? "check" : "alert"} size={13} />
                {c.text}
              </li>
            ))}
          </ul>
          <p className="text-[12px] text-muted">{schedule.advising_note ?? ADVISING}</p>
        </div>
        {actions}
      </footer>
    </article>
  );
}
