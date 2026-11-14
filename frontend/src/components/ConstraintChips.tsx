import { X } from "lucide-react";

import type { ConstraintSet, Day } from "../api/schemas";
import { ICON_STROKE } from "./ui/Icon";

const DAY_NAMES: Record<Day, string> = {
  M: "Mondays",
  T: "Tuesdays",
  W: "Wednesdays",
  R: "Thursdays",
  F: "Fridays",
  S: "Saturdays",
};

// frontend.md: rule chips cycle through these tag colors.
const CHIP_COLORS = ["bg-sq-sage", "bg-sq-clay", "bg-sq-sky", "bg-sq-butter", "bg-sq-lilac"];

/** "11:30:00" -> "11:30 AM" */
export function formatTime(value: string): string {
  const [h = 0, m = 0] = value.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

function sectionLabel(id: string): string {
  return id.split("|").pop() ?? id;
}

export interface Rule {
  key: string;
  label: string;
  /** The ConstraintSet with this one rule taken out. */
  without: () => ConstraintSet;
}

/** One chip per rule, exactly as the ConstraintSet from the API says it. */
export function rulesOf(c: ConstraintSet): Rule[] {
  const rules: Rule[] = [];
  const set = (patch: Partial<ConstraintSet>) => (): ConstraintSet => ({ ...c, ...patch });
  const drop = <K extends keyof ConstraintSet>(key: K, value: string) => (): ConstraintSet => ({
    ...c,
    [key]: ((c[key] as string[] | undefined) ?? []).filter((v) => v !== value),
  });

  if (c.earliest_start) {
    rules.push({
      key: "earliest_start",
      label: `No class before ${formatTime(c.earliest_start)}`,
      without: set({ earliest_start: null }),
    });
  }
  if (c.latest_end) {
    rules.push({
      key: "latest_end",
      label: `Done by ${formatTime(c.latest_end)}`,
      without: set({ latest_end: null }),
    });
  }
  const min = c.credit_min ?? null;
  const max = c.credit_max ?? null;
  if (min !== null || max !== null) {
    const label =
      min !== null && max !== null
        ? `${min} to ${max} credits`
        : max !== null
          ? `Up to ${max} credits`
          : `At least ${min} credits`;
    rules.push({ key: "credits", label, without: set({ credit_min: null, credit_max: null }) });
  }
  for (const day of c.days_off ?? []) {
    rules.push({ key: `day-${day}`, label: `${DAY_NAMES[day]} off`, without: drop("days_off", day) });
  }
  for (const code of c.include_courses ?? []) {
    rules.push({ key: `in-${code}`, label: `Take ${code}`, without: drop("include_courses", code) });
  }
  for (const code of c.exclude_courses ?? []) {
    rules.push({ key: `out-${code}`, label: `No ${code}`, without: drop("exclude_courses", code) });
  }
  for (const id of c.exclude_section_ids ?? []) {
    rules.push({
      key: `sec-${id}`,
      label: `Skip ${sectionLabel(id)}`,
      without: drop("exclude_section_ids", id),
    });
  }
  const methods = c.delivery_methods ?? [];
  if (methods.length > 0) {
    const names = methods.map((m) => m.charAt(0).toUpperCase() + m.slice(1));
    rules.push({
      key: "delivery",
      label: `${names.join(" or ")} only`,
      without: set({ delivery_methods: [] }),
    });
  }
  if (c.only_required) {
    rules.push({
      key: "only_required",
      label: "Only classes I need",
      without: set({ only_required: false }),
    });
  }
  if (c.allow_waitlist) {
    rules.push({
      key: "allow_waitlist",
      label: "Waitlist is fine",
      without: set({ allow_waitlist: false }),
    });
  }
  if (c.only_favorite_professors) {
    rules.push({
      key: "favorites",
      label: "Favorite professors only",
      without: set({ only_favorite_professors: false }),
    });
  }
  return rules;
}

interface ConstraintChipsProps {
  constraints: ConstraintSet;
  onChange: (next: ConstraintSet) => void;
  disabled?: boolean;
}

export function ConstraintChips({ constraints, onChange, disabled }: ConstraintChipsProps) {
  const rules = rulesOf(constraints);
  if (rules.length === 0) return null;
  return (
    <ul
      aria-label="Your rules"
      className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 md:flex-wrap md:overflow-visible"
    >
      {rules.map((rule, i) => (
        <li
          key={rule.key}
          className="flex min-h-11 shrink-0 items-center gap-2 rounded-full border border-line bg-surface pl-3.5 pr-1.5 text-sm"
        >
          <span
            aria-hidden="true"
            className={`size-2.5 rounded-[3px] ${CHIP_COLORS[i % CHIP_COLORS.length]}`}
          />
          <span>{rule.label}</span>
          <button
            type="button"
            aria-label={`Remove rule: ${rule.label}`}
            disabled={disabled}
            onClick={() => onChange(rule.without())}
            className="grid size-[30px] place-items-center rounded-full text-muted transition-colors duration-150 hover:bg-field hover:text-ink disabled:opacity-50"
          >
            <X size={14} strokeWidth={ICON_STROKE} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}
