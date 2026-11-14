// Small subject squares. Color is never the only signal: callers always write the
// code next to the square, and the square itself is hidden from screen readers.
const subjectColor: Record<string, string> = {
  CSE: "bg-sq-sage",
  REL: "bg-sq-clay",
  MATH: "bg-sq-sky",
  WDD: "bg-sq-sea",
};

export function subjectOf(courseCode: string): string {
  return courseCode.trim().split(/\s+/)[0]?.toUpperCase() ?? "";
}

export function TagSquare({ courseCode, size = 10 }: { courseCode: string; size?: number }) {
  const color = subjectColor[subjectOf(courseCode)] ?? "bg-sq-stone";
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 rounded-[3px] ${color}`}
      style={{ width: size, height: size }}
    />
  );
}
