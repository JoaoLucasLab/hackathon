import sampleAudit from "../../../fixtures/audit.json";
import type { DegreeAudit } from "../api/schemas";
import { TagSquare, subjectOf } from "./ui/TagSquare";

const positions = [
  "left-6 top-[76px] -rotate-6",
  "right-6 top-[60px] rotate-[5deg]",
  "left-0 top-[390px] rotate-[4deg]",
  "right-12 top-[370px] -rotate-[4deg]",
];

/** Decorative examples only: never imply a meeting time or a confirmed schedule. */
export function FloatingClassTickets({ audit }: { audit?: DegreeAudit }) {
  const requirements = (audit?.requirements ?? sampleAudit.requirements)
    .filter((requirement) => requirement.status === "not_met")
    .flatMap((requirement) => requirement.options?.[0]
      ? [{ code: requirement.options[0], name: requirement.name }]
      : []);
  // Spread subjects around the page when possible, then fill from the same audit.
  const subjects = new Set<string>();
  const varied = requirements.filter(({ code }) => {
    const subject = subjectOf(code);
    if (subjects.has(subject)) return false;
    subjects.add(subject);
    return true;
  });
  const tickets = [...varied, ...requirements.filter((course) => !varied.includes(course))].slice(0, 4);

  return (
    <div aria-hidden="true" className="class-tickets pointer-events-none absolute left-1/2 top-0 hidden h-full w-[calc(100vw_-_80px)] max-w-[1168px] -translate-x-1/2 min-[1100px]:block" data-testid="floating-class-tickets">
      {tickets.map((ticket, index) => (
        <div key={ticket.code} className={`slip-wrap absolute w-[164px] ${positions[index]}`}>
          <div className="slip ticket-enter [--cut:79px]" style={{ animationDelay: `${150 + index * 65}ms` }}>
            <div className="flex h-[79px] flex-col justify-center gap-1 px-4">
              <p className="text-sm font-semibold">{ticket.code}</p>
              <p className="line-clamp-2 text-xs leading-[1.35] text-muted">{ticket.name}</p>
            </div>
            <div className="slip-perf !mx-3" />
            <p className="flex items-center gap-1.5 px-4 py-3 text-[11px] text-muted">
              <TagSquare courseCode={ticket.code} />
              {audit ? "From your audit" : "From the sample audit"}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
