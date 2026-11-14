import { useState } from "react";

import { useProfessors, useRemainingRequirements, useScheduleExplanation } from "../api/queries";
import type { Professor, Schedule, ScheduledClass, Section } from "../api/schemas";
import { ProfessorChip } from "./ProfessorChip";
import { WeekCalendar } from "./WeekCalendar";
import {
  BlockTag,
  blockLabel,
  plural,
  seatsLine,
  sectionCode,
  warningText,
  whenLine,
} from "./scheduleFormat";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { TagSquare } from "./ui/TagSquare";

const ADVISING = "Confirm with BYU-Idaho Academic Advising.";

function Warning({ message }: { message: string }) {
  // A warning, not an error: `warn` text, never red, never role="alert".
  return (
    <p className="flex items-start gap-1.5 text-[13px] text-warn">
      <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
      <span>{warningText(message)}</span>
    </p>
  );
}

/** Professors by id, or null while they load (or failed to load): then show nothing. */
type ProfessorIndex = Map<string, Professor> | null;

function Professors({ section, byId }: { section: Section; byId: ProfessorIndex }) {
  if (byId === null) return null;
  const profs = (section.instructor_ids ?? [])
    .map((id) => byId.get(id))
    .filter((p): p is Professor => Boolean(p));
  if (profs.length === 0) return <p className="text-sm text-muted">Professor not listed yet</p>;
  return (
    <>
      {profs.map((p) => (
        <ProfessorChip key={p.id} professor={p} />
      ))}
    </>
  );
}

function Backups({ backups, byId }: { backups: Section[]; byId: ProfessorIndex }) {
  return (
    <ul className="flex flex-col gap-3 rounded-tag bg-field p-3">
      {backups.slice(0, 2).map((b) => {
        const block = blockLabel(b);
        return (
          <li key={b.id} className="flex flex-col gap-1">
            <p className="text-sm">
              <span className="font-semibold">{sectionCode(b)}</span>
              <span className="tabular-nums text-muted"> {whenLine(b)}</span>
            </p>
            {block && <BlockTag label={block} />}
            <Professors section={b} byId={byId} />
            <p className="text-[13px] tabular-nums text-muted">{seatsLine(b)}</p>
          </li>
        );
      })}
    </ul>
  );
}

function ClassRow({
  item,
  fills,
  byId,
}: {
  item: ScheduledClass;
  fills: string[];
  byId: ProfessorIndex;
}) {
  const [open, setOpen] = useState(false);
  const s = item.section;
  const block = blockLabel(s);
  const backups = (item.backups ?? []).slice(0, 2);
  const backupsId = `backups-${s.id}`;

  return (
    <li className="flex flex-col gap-2 border-b border-line-soft py-4 last:border-b-0">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-1.5">
            <TagSquare courseCode={s.course_code} size={14} />
          </span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <h3 className="text-base">
              <span className="font-semibold">{sectionCode(s)}</span>
              <span className="font-normal text-muted"> {s.title}</span>
            </h3>
            <p className="text-sm tabular-nums text-muted">{whenLine(s)}</p>
          </div>
        </div>
        <p className="shrink-0 text-sm tabular-nums text-muted">{plural(s.credits, "credit")}</p>
      </div>
      <div className="flex flex-col gap-1.5 pl-[26px]">
        <p className="text-sm">
          {fills.length > 0 ? (
            <>
              <span className="text-muted">Fills: </span>
              {fills.join(", ")}
            </>
          ) : (
            <span className="text-muted">Not tied to a remaining requirement</span>
          )}
        </p>
        {block && <BlockTag label={block} />}
        <Professors section={s} byId={byId} />
        <p className="text-[13px] tabular-nums text-muted">{seatsLine(s, item.waitlisted)}</p>
        {(item.warnings ?? []).map((w, i) => (
          <Warning key={i} message={w.message} />
        ))}
        {backups.length > 0 && (
          <div className="flex flex-col gap-2">
            <Button
              variant="text"
              className="self-start"
              aria-expanded={open}
              aria-controls={backupsId}
              onClick={() => setOpen((o) => !o)}
            >
              {open ? "Hide backup sections" : `Show ${plural(backups.length, "backup section")}`}
              <Icon
                name="chevronDown"
                size={16}
                className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`}
              />
            </Button>
            <div id={backupsId} hidden={!open}>
              {open && <Backups backups={backups} byId={byId} />}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

/** Plain labels for the solver's structured rule names, used when there is no text. */
function ruleLabel(key: string): string {
  const [name, arg] = key.split(":");
  const days: Record<string, string> = {
    M: "Monday",
    T: "Tuesday",
    W: "Wednesday",
    R: "Thursday",
    F: "Friday",
    S: "Saturday",
  };
  switch (name) {
    case "earliest_start":
      return "Start time";
    case "latest_end":
      return "End time";
    case "credit_range":
      return "Credit range";
    case "days_off":
      return arg ? `${days[arg] ?? arg} off` : "Days off";
    case "favorite_professor":
      return "Favorite professors";
    default:
      return key.replace(/_/g, " ");
  }
}

function Why({ schedule }: { schedule: Schedule }) {
  const explanation = useScheduleExplanation(schedule);
  const met = schedule.why.preferences_met ?? [];
  const missed = schedule.why.preferences_missed ?? [];

  if (explanation.isPending) {
    return (
      <div role="status" aria-label="Writing why this schedule fits" className="flex flex-col gap-2">
        <div className="h-5 w-4/5 rounded bg-field motion-safe:animate-pulse" />
        <div className="h-5 w-3/5 rounded bg-field motion-safe:animate-pulse" />
      </div>
    );
  }

  const text = explanation.data?.available ? explanation.data : null;
  return (
    <section aria-labelledby="why-title" className="flex flex-col gap-3">
      <h3 id="why-title" className="text-sm font-semibold">
        Why this schedule
      </h3>
      {text?.why ? (
        <blockquote className="max-w-[60ch] font-serif text-[23px] leading-[1.4] tracking-[-0.015em]">
          {text.why}
        </blockquote>
      ) : (
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-muted">
            {explanation.isError
              ? "We couldn't load the summary. These are the rules it was built from."
              : "No written summary for this one. These are the rules it was built from."}
          </p>
          {met.length > 0 && <p>Keeps: {met.map(ruleLabel).join(", ")}</p>}
          {missed.length > 0 && <p>Misses: {missed.map(ruleLabel).join(", ")}</p>}
        </div>
      )}
      {text && text.tradeoffs && text.tradeoffs.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-sm font-semibold">Trade-offs</h4>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
            {text.tradeoffs.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

interface ScheduleDetailProps {
  schedule: Schedule;
  onBack: () => void;
}

/** One schedule: the "why", the week calendar, class rows with professors and backups. */
export function ScheduleDetail({ schedule, onBack }: ScheduleDetailProps) {
  const professors = useProfessors();
  const requirements = useRemainingRequirements();
  const byId: ProfessorIndex = professors.data
    ? new Map(professors.data.map((p) => [p.id, p]))
    : null;
  const reqNames = new Map((requirements.data ?? []).map((r) => [r.id, r.name]));
  const titleId = `detail-${schedule.id}`;

  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-6">
      <Button variant="text" className="self-start" onClick={onBack}>
        <Icon name="chevronLeft" size={16} />
        All schedules
      </Button>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2.5">
          <h1 id={titleId} className="font-serif text-[40px] font-normal leading-none md:text-[52px]">
            Option {schedule.rank}
          </h1>
          {schedule.rank === 1 && (
            <span className="rounded-full bg-ink px-2 py-0.5 text-xs text-surface">Best fit</span>
          )}
        </div>
        <p className="text-sm tabular-nums text-muted">
          {plural(schedule.total_credits, "credit")}, {plural(schedule.classes.length, "class")}
        </p>
      </div>

      <Why schedule={schedule} />

      {(schedule.warnings ?? []).map((w, i) => (
        <Warning key={i} message={w.message} />
      ))}

      <section aria-label="Week" className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Week</h3>
        <WeekCalendar schedule={schedule} />
      </section>

      <ul aria-label="Classes" className="rounded-card border border-line bg-surface px-6">
        {schedule.classes.map((c) => (
          <ClassRow
            key={c.section.id}
            item={c}
            byId={byId}
            fills={(c.requirement_ids ?? []).map((id) => reqNames.get(id) ?? id)}
          />
        ))}
      </ul>
      {professors.isError && (
        <p className="text-sm text-muted">Professor details couldn't load. Try again later.</p>
      )}

      <p className="text-sm font-medium">{schedule.advising_note ?? ADVISING}</p>
    </article>
  );
}
