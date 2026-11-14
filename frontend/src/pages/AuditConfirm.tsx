import { useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { queryKeys, useConfirmAudit } from "../api/queries";
import type {
  AuditCourse,
  AuditRequirement,
  DegreeAudit,
  Track,
  ValidationFlag,
} from "../api/schemas";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Empty } from "../components/ui/Empty";
import { Icon } from "../components/ui/Icon";
import { PageFrame } from "../components/ui/PageFrame";
import { TagSquare } from "../components/ui/TagSquare";
import {
  STALE,
  editableFlags,
  editorFor,
  fieldLabel,
  getAt,
  parsePath,
  setAt,
  type Path,
} from "./auditFields";

const TRACKS: { value: Track; label: string }[] = [
  { value: "fall_winter", label: "Fall & Winter" },
  { value: "winter_spring", label: "Winter & Spring" },
  { value: "spring_fall", label: "Spring & Fall" },
  { value: "online", label: "Online (no track)" },
];

const REQUIREMENT_STATUS: Record<AuditRequirement["status"], string> = {
  complete: "Complete",
  in_progress: "In progress",
  not_met: "Not met",
};

const COURSE_STATUS: Record<AuditCourse["status"], string> = {
  complete: "Complete",
  in_progress: "In progress",
  transfer: "Transfer",
};

function credits(n: number): string {
  return `${n} ${n === 1 ? "credit" : "credits"}`;
}

function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/** One flagged value with its message and an input to correct it. */
function FlagEditor({
  flag,
  audit,
  edited,
  onChange,
}: {
  flag: ValidationFlag;
  audit: DegreeAudit;
  edited: boolean;
  onChange: (path: Path, value: unknown) => void;
}) {
  const inputId = useId();
  const messageId = useId();
  const path = parsePath(flag.field);
  const kind = editorFor(path);
  const value = getAt(audit, path);
  const label = fieldLabel(audit, path);

  let control = null;
  if (kind === "code") {
    control = (
      <input
        id={inputId}
        type="text"
        value={typeof value === "string" ? value : ""}
        aria-describedby={messageId}
        onChange={(e) => onChange(path, e.target.value.toUpperCase())}
        className="min-h-11 w-40 rounded-btn border border-line bg-surface px-3 uppercase"
      />
    );
  } else if (kind === "number") {
    control = (
      <input
        id={inputId}
        type="number"
        min={0}
        step={0.5}
        value={typeof value === "number" ? value : 0}
        aria-describedby={messageId}
        onChange={(e) => onChange(path, Number(e.target.value))}
        className="min-h-11 w-28 rounded-btn border border-line bg-surface px-3 tabular-nums"
      />
    );
  } else if (kind === "course-status" || kind === "requirement-status") {
    const options = kind === "course-status" ? COURSE_STATUS : REQUIREMENT_STATUS;
    control = (
      <select
        id={inputId}
        value={typeof value === "string" ? value : ""}
        aria-describedby={messageId}
        onChange={(e) => onChange(path, e.target.value)}
        className="min-h-11 rounded-btn border border-line bg-surface px-3"
      >
        {Object.entries(options).map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    );
  }

  return (
    <li
      data-flag={flag.kind}
      className="flex flex-col gap-3 border-b border-line-soft px-6 py-5 last:border-b-0"
    >
      <p id={messageId} className="flex items-start gap-2 text-[13px] text-warn">
        <Icon name={edited ? "check" : "alert"} size={16} className="mt-0.5 shrink-0" />
        <span>
          {edited ? "Edited. " : "Check this: "}
          {flag.message}
        </span>
      </p>
      {control && (
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor={inputId} className="text-sm font-medium">
            {label}
          </label>
          {control}
        </div>
      )}
    </li>
  );
}

function CourseLine({ course }: { course: AuditCourse }) {
  const grade =
    course.status === "in_progress" ? "pending grade" : course.grade ? course.grade : "no grade";
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      <TagSquare courseCode={course.course_code} />
      <span className="font-semibold">{course.course_code}</span>
      <span className="text-muted">{course.title}</span>
      <span className="text-muted">
        · {grade} · {course.term}
      </span>
      {course.status === "transfer" && (
        <span className="text-muted">
          · Transfer{course.equivalent_of ? `, counts as ${course.equivalent_of}` : ""}
        </span>
      )}
    </li>
  );
}

function RequirementDetail({
  req,
  courses,
  flagged,
}: {
  req: AuditRequirement;
  courses: Map<string, AuditCourse>;
  flagged: boolean;
}) {
  const counted = req.courses_counted ?? [];
  const options = req.options ?? [];
  return (
    <li className="flex flex-col gap-2 border-t border-line-soft py-4 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p>
          <span className="font-semibold">{req.name}</span>
          <span className="text-muted"> · {REQUIREMENT_STATUS[req.status]}</span>
          {flagged && <span className="text-[13px] text-warn"> · Needs a check</span>}
        </p>
        <p className="text-sm tabular-nums text-muted">
          {req.credits_needed > 0 ? `${credits(req.credits_needed)} still needed` : "Done"}
        </p>
      </div>
      {counted.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label={`Courses counted for ${req.name}`}>
          {counted.map((code) => {
            const course = courses.get(code);
            return course ? (
              <CourseLine key={code} course={course} />
            ) : (
              <li key={code} className="text-sm">
                {code}
              </li>
            );
          })}
        </ul>
      )}
      {req.status !== "complete" && options.length > 0 && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
          <span>{options.length === 1 ? "Fill it with" : "Fill it with one of"}</span>
          {options.map((code) => (
            <span
              key={code}
              className="inline-flex items-center gap-1.5 rounded-tag bg-field px-2 py-0.5 text-ink"
            >
              <TagSquare courseCode={code} />
              {code}
            </span>
          ))}
        </p>
      )}
    </li>
  );
}

function groupStatus(reqs: AuditRequirement[]): string {
  if (reqs.every((r) => r.status === "complete")) return "Complete";
  if (reqs.every((r) => r.status !== "not_met")) return "In progress";
  return "Not met";
}

export function AuditConfirm() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const confirm = useConfirmAudit();
  const trackName = useId();
  const parsed = queryClient.getQueryData<DegreeAudit>(queryKeys.auditDraft);
  const [audit, setAudit] = useState<DegreeAudit | undefined>(parsed);
  const [edited, setEdited] = useState<Set<string>>(new Set());

  const flags = useMemo(() => parsed?.validation_flags ?? [], [parsed]);

  if (!parsed || !audit) {
    return (
      <PageFrame title="Check your audit">
        <Empty
          message="There is no audit to check yet. Upload your degree audit first."
          actionLabel="Upload my audit"
          onAction={() => navigate("/audit")}
        />
      </PageFrame>
    );
  }

  const stale = flags.find((f) => f.kind === STALE);
  const toFix = editableFlags(flags);
  const needsTrack = parsed.track == null;
  const requirements = audit.requirements ?? [];
  const courses = new Map((audit.courses ?? []).map((c) => [c.course_code, c]));
  const flaggedRequirements = new Set(
    toFix
      .map((f) => parsePath(f.field))
      .filter((p) => p[0] === "requirements" && typeof p[1] === "number")
      .map((p) => p[1] as number),
  );
  const groups = new Map<string, { req: AuditRequirement; index: number }[]>();
  requirements.forEach((req, index) => {
    groups.set(req.group, [...(groups.get(req.group) ?? []), { req, index }]);
  });
  const stillNeeded = requirements
    .filter((r) => r.status !== "complete")
    .reduce((sum, r) => sum + r.credits_needed, 0);

  const change = (field: string) => (path: Path, value: unknown) => {
    setAudit((current) => (current ? setAt(current, path, value) : current));
    setEdited((current) => new Set(current).add(field));
  };

  const save = () =>
    confirm.mutate(
      { ...audit, validation_flags: [] },
      { onSuccess: () => navigate("/requirements") },
    );

  const summary = [
    audit.major,
    audit.minor ? `minor in ${audit.minor}` : null,
    `${audit.catalog_year} catalog`,
    `audit from ${longDate(audit.audit_date)}`,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <PageFrame
      title="Check your audit"
      lead="Make sure we read it right. Fix anything marked, then save."
      footnote="Confirm with BYU-Idaho Academic Advising."
    >
      <p className="text-[17px]">{summary}</p>
      <p className="text-sm tabular-nums text-muted">
        {credits(audit.total_credits_earned)} earned of {audit.total_credits_required} required,{" "}
        {credits(stillNeeded)} still needed in the requirements below
      </p>

      {stale && (
        <Card role="status" className="flex flex-col items-start gap-3">
          <p className="flex items-start gap-2 text-warn">
            <Icon name="alert" className="mt-0.5 shrink-0" />
            <span>
              This audit is from {longDate(audit.audit_date)}. Download a fresh one so it shows
              your latest grades and classes.
            </span>
          </p>
          <Button onClick={() => navigate("/audit")}>Upload a fresh audit</Button>
        </Card>
      )}

      {needsTrack && (
        <fieldset className="flex flex-col gap-3 rounded-card border border-line bg-surface p-6">
          <legend className="px-1 font-semibold">Which track are you on?</legend>
          <p className="text-sm text-muted">
            Your audit does not show it. Your track decides which semesters you take classes on
            campus.
          </p>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {TRACKS.map((t) => (
              <label key={t.value} className="flex min-h-11 cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name={trackName}
                  value={t.value}
                  checked={audit.track === t.value}
                  onChange={() => setAudit({ ...audit, track: t.value })}
                  className="size-5 accent-ink"
                />
                {t.label}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {toFix.length > 0 && (
        <section aria-labelledby="to-check" className="flex flex-col gap-3">
          <h2 id="to-check" className="font-semibold">
            {toFix.length === 1 ? "1 value to check" : `${toFix.length} values to check`}
          </h2>
          <ul className="rounded-card border border-line bg-surface">
            {toFix.map((flag) => (
              <FlagEditor
                key={flag.field + flag.kind}
                flag={flag}
                audit={audit}
                edited={edited.has(flag.field)}
                onChange={change(flag.field)}
              />
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="groups" className="flex flex-col gap-3">
        <h2 id="groups" className="font-semibold">
          Requirements
        </h2>
        {requirements.length === 0 ? (
          <p className="text-muted">We found no requirements in this audit.</p>
        ) : (
          <ul className="rounded-card border border-line bg-surface">
            {[...groups.entries()].map(([group, items]) => {
              const reqs = items.map((i) => i.req);
              const left = reqs.reduce((s, r) => s + r.credits_needed, 0);
              const anyFlag = items.some((i) => flaggedRequirements.has(i.index));
              return (
                <li key={group} className="border-b border-line-soft last:border-b-0">
                  <details open={anyFlag || undefined}>
                    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 px-6 py-4">
                      <span className="flex items-center gap-2">
                        <Icon name="chevronDown" size={16} className="shrink-0" />
                        <span className="font-semibold">{group}</span>
                        <span className="text-muted">· {groupStatus(reqs)}</span>
                      </span>
                      <span className="text-sm tabular-nums text-muted">
                        {left > 0 ? `${credits(left)} left` : "Done"}
                      </span>
                    </summary>
                    <ul className="px-6 pb-2">
                      {items.map(({ req, index }) => (
                        <RequirementDetail
                          key={req.id}
                          req={req}
                          courses={courses}
                          flagged={flaggedRequirements.has(index)}
                        />
                      ))}
                    </ul>
                  </details>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {(audit.courses ?? []).length > 0 && (
        <details className="rounded-card border border-line bg-surface">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-6 py-4">
            <Icon name="chevronDown" size={16} className="shrink-0" />
            <span className="font-semibold">All courses on your record</span>
            <span className="text-muted">· {(audit.courses ?? []).length}</span>
          </summary>
          <ul className="flex flex-col gap-2 px-6 pb-5" aria-label="Courses on your record">
            {(audit.courses ?? []).map((c, i) => (
              <CourseLine key={`${c.course_code}-${i}`} course={c} />
            ))}
          </ul>
        </details>
      )}

      <div className="flex flex-col items-start gap-3">
        <Button
          variant="primary"
          disabled={audit.track == null || confirm.isPending}
          aria-busy={confirm.isPending}
          onClick={save}
        >
          Save my audit
        </Button>
        {audit.track == null && (
          <p className="text-sm text-muted">Choose your track above to save.</p>
        )}
        {confirm.isError && (
          <p role="alert" className="flex items-start gap-2">
            <Icon name="alert" className="mt-0.5 shrink-0" />
            We couldn't save your audit. Check your connection and try again.
          </p>
        )}
      </div>
    </PageFrame>
  );
}
