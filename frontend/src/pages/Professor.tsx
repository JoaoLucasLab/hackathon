import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorStatus, useProfessor } from "../api/queries";
import type { Professor as ProfessorType, ProfessorSource } from "../api/schemas";
import { ProfessorChip, professorName } from "../components/ProfessorChip";
import { Empty } from "../components/ui/Empty";
import { ErrorState } from "../components/ui/ErrorState";
import { Loading } from "../components/ui/Loading";
import { PageFrame } from "../components/ui/PageFrame";

const sections: { kind: ProfessorSource["kind"]; label: string }[] = [
  { kind: "biography", label: "Biography" },
  { kind: "education", label: "Education" },
  { kind: "interests", label: "Interests" },
  { kind: "research", label: "Research" },
  { kind: "work_experience", label: "Work experience" },
];

function fetchedOn(value: string): string {
  return new Date(value).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

/** Where a fact came from: a link to the public page and the day it was read. */
function SourceLine({ source }: { source: ProfessorSource }) {
  return <p className="text-[13px] text-muted">
    <a href={source.source_url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-ink">Source<span className="sr-only"> for {source.kind.replaceAll("_", " ")} (opens in a new tab)</span></a>
    {" · "}Fetched {fetchedOn(source.fetched_at)}
  </p>;
}

function Facts({ professor }: { professor: ProfessorType }) {
  const sources = professor.sources ?? [];
  const bio = sources.find((s) => s.kind === "biography");
  const shown = sections
    .map((section) => ({ ...section, source: sources.find((s) => s.kind === section.kind && s.value.trim()) }))
    .filter((section) => section.source && !(section.kind === "biography" && professor.bio_summary && bio));
  return <div className="flex flex-col gap-6">
    {professor.bio_summary && bio && <section aria-labelledby="bio-heading" className="flex flex-col gap-2">
      <h2 id="bio-heading" className="text-sm font-semibold uppercase tracking-wide text-muted">Summary</h2>
      <p className="max-w-[60ch] text-[17px] leading-[1.5]">{professor.bio_summary}</p>
      <SourceLine source={bio} />
    </section>}
    {shown.map(({ kind, label, source }) => <section key={kind} aria-labelledby={`${kind}-heading`} className="flex flex-col gap-2">
      <h2 id={`${kind}-heading`} className="text-sm font-semibold uppercase tracking-wide text-muted">{label}</h2>
      <p className="max-w-[60ch] whitespace-pre-line">{source!.value}</p>
      <SourceLine source={source!} />
    </section>)}
    <section aria-labelledby="winter-heading" className="flex flex-col gap-2">
      <h2 id="winter-heading" className="text-sm font-semibold uppercase tracking-wide text-muted">Winter 2027 courses</h2>
      {professor.winter_courses?.length
        ? <ul className="flex flex-wrap gap-2">{professor.winter_courses.map((code) => <li key={code} className="rounded-full border border-line bg-surface px-3 py-1 text-sm">{code}</li>)}</ul>
        : <p className="text-muted">No Winter 2027 courses listed yet.</p>}
      <p className="text-[13px] text-muted">From the Winter 2027 class schedule.</p>
    </section>
    {!shown.length && !(professor.bio_summary && bio) && <p className="text-muted">This professor's public profile has no details yet.</p>}
  </div>;
}

export function Professor() {
  const { professorId = "" } = useParams();
  const professor = useProfessor(professorId);
  const navigate = useNavigate();
  return <PageFrame title={professor.data ? professorName(professor.data) : "Professor"} footnote="Facts come only from official public university pages. No ratings are shown.">
    <Link to="/professors" className="-mt-4 inline-flex min-h-11 items-center gap-2 self-start text-sm text-muted hover:text-ink"><ArrowLeft size={16} aria-hidden="true" />All professors</Link>
    {professor.isPending ? <Loading label="Loading professor" />
      : professor.isError ? (errorStatus(professor.error) === 404
        ? <Empty message="We couldn't find this professor. Go back and search again." actionLabel="Search professors" onAction={() => navigate("/professors")} />
        : <ErrorState message="We couldn't load this professor. Check your connection and try again." onRetry={() => void professor.refetch()} />)
      : <article className="flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <p className="text-muted">{[professor.data.title, professor.data.department].filter(Boolean).join(", ")}</p>
          <ProfessorChip professor={professor.data} />
        </div>
        <Facts professor={professor.data} />
      </article>}
  </PageFrame>;
}
