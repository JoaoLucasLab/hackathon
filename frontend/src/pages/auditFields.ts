import type { DegreeAudit, ValidationFlag } from "../api/schemas";

/** A path from a validation flag, e.g. `requirements[3].options[0]`, as keys. */
export type Path = (string | number)[];

export function parsePath(field: string): Path {
  const path: Path = [];
  for (const part of field.split(".")) {
    const match = /^([^[]+)((?:\[\d+\])*)$/.exec(part);
    if (!match) return [];
    path.push(match[1]);
    for (const index of match[2].matchAll(/\[(\d+)\]/g)) path.push(Number(index[1]));
  }
  return path;
}

export function getAt(root: unknown, path: Path): unknown {
  let value: unknown = root;
  for (const key of path) {
    if (value === null || typeof value !== "object") return undefined;
    value = (value as Record<string | number, unknown>)[key];
  }
  return value;
}

/** A copy of `root` with the value at `path` replaced. `root` is not changed. */
export function setAt<T>(root: T, path: Path, value: unknown): T {
  if (path.length === 0) return value as T;
  const [key, ...rest] = path;
  const node = root as unknown as Record<string | number, unknown>;
  const copy = (Array.isArray(node) ? [...node] : { ...node }) as Record<string | number, unknown>;
  copy[key] = setAt(node[key], rest, value);
  return copy as unknown as T;
}

export type EditorKind = "code" | "number" | "course-status" | "requirement-status" | "none";

/** Which control edits the value a flag points at. */
export function editorFor(path: Path): EditorKind {
  const last = path.filter((k) => typeof k === "string").at(-1);
  if (path[0] === "audit_date") return "none";
  if (last === "status") return path[0] === "courses" ? "course-status" : "requirement-status";
  if (last === "course_code" || last === "equivalent_of" || last === "options") return "code";
  if (last === "courses_counted") return "code";
  if (typeof last === "string" && last.includes("credits")) return "number";
  return "none";
}

/** A short, human name for the value a flag points at, for its input label. */
export function fieldLabel(audit: DegreeAudit, path: Path): string {
  const [root, index, key] = path;
  if (root === "total_credits_earned") return "Total credits earned";
  if (root === "courses" && typeof index === "number") {
    const course = audit.courses?.[index];
    const name = course ? course.course_code : `Course ${index + 1}`;
    if (key === "course_code") return `Course code for ${course?.title ?? name}`;
    if (key === "equivalent_of") return `BYU-Idaho equivalent of ${name}`;
    if (key === "status") return `Status of ${name}`;
    return name;
  }
  if (root === "requirements" && typeof index === "number") {
    const req = audit.requirements?.[index];
    const name = req?.name ?? `Requirement ${index + 1}`;
    if (key === "credits_needed") return `Credits still needed for ${name}`;
    if (key === "status") return `Status of ${name}`;
    if (key === "options") return `Course option for ${name}`;
    if (key === "courses_counted") return `Course counted for ${name}`;
    return name;
  }
  return "Value";
}

export const STALE = "stale_audit";

export function editableFlags(flags: ValidationFlag[]): ValidationFlag[] {
  return flags.filter((f) => f.kind !== STALE);
}
