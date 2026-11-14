import { useMutation } from "@tanstack/react-query";
import { ArrowUp, Mail, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, unwrap } from "../api/client";
import { useProfessors } from "../api/queries";
import type { components } from "../api/types";
import { ProfessorChip, professorName } from "../components/ProfessorChip";
import { Button } from "../components/ui/Button";
import { Empty } from "../components/ui/Empty";
import { ErrorState } from "../components/ui/ErrorState";
import { Loading } from "../components/ui/Loading";
import { PageFrame } from "../components/ui/PageFrame";

type Goal = components["schemas"]["MentorGoal"];
type Professor = components["schemas"]["Professor"];
type MentorMatch = components["schemas"]["MentorMatch"];
type MentorReason = components["schemas"]["MentorReason"];

/** What a search found: mentors for a topic, professors by name or subject, or nothing. */
type SearchResult =
  | { kind: "mentors"; tags: string[]; matches: MentorMatch[] }
  | { kind: "directory"; professors: Professor[] }
  | { kind: "none" };

const MAX_MENTORS = 5;
const EMPTY_TOPIC = "No professors match this topic yet. Try other words, a professor's name, or one of the topics below.";

function reasonLine(reason: MentorReason): string {
  switch (reason.kind) {
    case "topic_overlap": return `Lists ${reason.detail} as an interest`;
    case "took_class": return `You took ${reason.source.ref} with this professor`;
    case "teaches_winter": return `Teaches ${reason.source.ref} in Winter 2027`;
    case "lists_research": return "Mentors undergraduate research";
  }
}

/** Claude's sentence when there is one, otherwise the structured reasons as a list. */
function Reasons({ match }: { match: MentorMatch }) {
  if (match.reason_text) return <p className="text-sm">{match.reason_text}</p>;
  return <ul aria-label="Why this professor" className="list-disc pl-5 text-sm">{match.reasons.map((r, i) => <li key={i}>{reasonLine(r)}</li>)}</ul>;
}
const goals: { value: Goal; label: string; color: string }[] = [
  { value: "research", label: "Research", color: "bg-sq-sage" },
  { value: "recommendation letter", label: "Recommendation letter", color: "bg-sq-clay" },
  { value: "TA job", label: "TA job", color: "bg-sq-sky" },
  { value: "internship referral", label: "Internship", color: "bg-sq-butter" },
];

function EmailDraft({ professor, goal, tags, onClose }: { professor: Professor; goal: Goal; tags: string[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [mentionGrade, setMentionGrade] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const draft = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/mentors/{professor_id}/email-draft", {
      params: { path: { professor_id: professor.id } }, body: { goal, mention_grade: mentionGrade, tags },
    })),
    onSuccess: (data) => { setSubject(data.subject); setBody(data.body); setCopyStatus(""); },
  });
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} onCancel={onClose} onClose={onClose} aria-labelledby="draft-title" className="m-auto w-[calc(100%_-_40px)] max-w-[600px] rounded-card border border-line bg-surface p-6 text-ink backdrop:bg-ink/20">
    <div className="mb-5 flex items-center justify-between gap-3"><h2 id="draft-title" className="font-serif text-[30px]">Draft an email</h2><button type="button" aria-label="Close email draft" onClick={onClose} className="grid size-11 place-items-center rounded-btn hover:bg-field"><X size={20} /></button></div>
    <p className="mb-4 text-sm text-muted">To {professorName(professor)}. Edit the draft, then copy it to your email app.</p>
    <label className="mb-4 flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={mentionGrade} onChange={(e) => setMentionGrade(e.target.checked)} className="size-4 accent-ink" />Mention my grade</label>
    <Button variant={draft.data ? "secondary" : "primary"} disabled={draft.isPending} onClick={() => draft.mutate()}>{draft.isPending ? "Drafting email…" : draft.data ? "Regenerate draft" : "Create draft"}</Button>
    {draft.isError && <p role="alert" className="mt-4 text-sm">We couldn't create this draft. Try again.</p>}
    {draft.data && <div className="mt-5 flex flex-col gap-3">{draft.data.class_named && <p className="text-sm text-muted">Mentions {draft.data.class_named}, the class you took with this professor.</p>}<label htmlFor="draft-subject" className="text-sm font-medium">Subject</label><input id="draft-subject" value={subject} onChange={(e) => setSubject(e.target.value)} className="rounded-btn border border-line p-3" /><label htmlFor="draft-body" className="text-sm font-medium">Message</label><textarea id="draft-body" rows={9} value={body} onChange={(e) => setBody(e.target.value)} className="rounded-btn border border-line p-3 text-sm" /><Button variant="primary" onClick={async () => { try { await navigator.clipboard.writeText(`${subject}\n\n${body}`); setCopyStatus("Copied to clipboard."); } catch { setCopyStatus("Couldn't copy. Select the draft and copy it manually."); } }}>Copy draft</Button><p role="status" className="text-sm text-muted">{copyStatus}</p></div>}
  </dialog>;
}

export function MentorFinder() {
  const professors = useProfessors();
  const [goal, setGoal] = useState<Goal>("research");
  const [topic, setTopic] = useState("");
  const [emailProfessor, setEmailProfessor] = useState<Professor | null>(null);
  const [showAll, setShowAll] = useState(false);
  const search = useMutation<SearchResult, Error, { text: string; goal: Goal }>({
    mutationFn: async ({ text, goal }) => {
      // Claude maps the topic to tags that already exist on profiles. It never adds one.
      const { tags } = unwrap(await api.POST("/api/mentors/topic", { body: { topic: text } }));
      if (tags?.length) {
        const matches = unwrap(await api.POST("/api/mentors/search", { body: { goal, tags } }));
        if (matches.length) return { kind: "mentors", tags, matches: matches.slice(0, MAX_MENTORS) };
      }
      const found = unwrap(await api.GET("/api/professors", { params: { query: { q: text } } }));
      return found.length ? { kind: "directory", professors: found } : { kind: "none" };
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const text = topic.trim();
    setShowAll(false);
    if (text) search.mutate({ text, goal }); else search.reset();
  }
  function clear() { setTopic(""); search.reset(); }
  // Read professors from the shared list, so a star changed here shows at once.
  const current = (p: Professor) => professors.data?.find((q) => q.id === p.id) ?? p;
  const result = search.data;
  const matches = result?.kind === "mentors" ? result.matches : undefined;
  const rows = result?.kind === "mentors" ? result.matches.map((m) => current(m.professor))
    : result?.kind === "directory" ? result.professors.map(current)
    : result?.kind === "none" ? [] : professors.data ?? [];
  const shown = showAll || matches ? rows : rows.slice(0, 3);
  const tags = [...new Set((professors.data ?? []).flatMap((p) => p.topic_tags ?? []))].slice(0, 6);
  const emailTags = result?.kind === "mentors" ? result.tags : [];
  return <PageFrame title="Find a professor to ask" home wide footnote="Professor information comes from public university pages. Outreach emails are drafts for you to copy.">
    <div className="mx-auto flex w-full max-w-[620px] flex-col gap-5">
      <div aria-label="Your goal" className="flex flex-wrap justify-center gap-2">{goals.map((g) => <button key={g.value} type="button" aria-pressed={goal === g.value} onClick={() => { setGoal(g.value); if (search.variables) search.mutate({ ...search.variables, goal: g.value }); }} className={`flex min-h-11 items-center gap-2 rounded-full border bg-surface px-3 text-sm ${goal === g.value ? "border-ink font-semibold" : "border-line"}`}><span aria-hidden="true" className={`size-2.5 rounded-[4px] ${g.color}`} />{g.label}</button>)}</div>
      <form onSubmit={submit} className="flex items-center gap-2 rounded-card border border-line bg-surface p-2 shadow-[0_0_0_6px_var(--halo)] focus-within:border-ink"><label htmlFor="professor-topic" className="sr-only">Search professors by name, subject, or topic</label><input id="professor-topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What would you like to explore?" className="min-w-0 flex-1 bg-transparent px-3 py-2 outline-none" /><button type="submit" aria-label="Find professors" disabled={professors.isPending || professors.isError || search.isPending} className="grid size-11 shrink-0 place-items-center rounded-btn bg-ink text-surface disabled:opacity-50"><ArrowUp size={18} /></button></form>
      {tags.length > 0 && <p className="text-center text-[13px] text-muted">Topics include {tags.join(", ")}.</p>}
    </div>
    <section aria-label="Professors" className="mt-5">
      {professors.isPending || search.isPending ? <Loading label="Finding professors" /> : professors.isError || search.isError ? <ErrorState message="We couldn't load professors. Check your connection and try again." onRetry={() => { if (professors.isError) void professors.refetch(); else if (search.variables) search.mutate(search.variables); }} /> : rows.length === 0 ? <Empty message={EMPTY_TOPIC} actionLabel="Clear search" onAction={clear} /> : <>
        {matches && <p className="mb-4 text-sm text-muted">Showing {matches.length === 1 ? "1 professor" : `the top ${matches.length} professors`} for {result?.kind === "mentors" ? result.tags.join(", ") : ""}.</p>}
        <div className="grid gap-6 md:grid-cols-3">{shown.map((professor) => {
          const match = matches?.find((m) => m.professor.id === professor.id);
          return <article key={professor.id} className="slip-wrap"><div className="slip relative h-full [--cut:132px]">
            <div className="flex h-[132px] flex-col justify-center gap-2 px-6"><span aria-hidden="true" className="font-serif text-[36px] leading-none">{professor.first_name.charAt(0)}{professor.last_name.charAt(0)}</span><h2 className="font-semibold"><Link to={`/professors/${encodeURIComponent(professor.id)}`} className="underline-offset-2 hover:underline">{professorName(professor)}</Link></h2><p className="text-sm text-muted">{professor.department}</p></div>
            <div className="slip-perf" /><div className="flex flex-col gap-3 px-6 py-5">
              {match ? <Reasons match={match} /> : <p className="text-sm">{professor.bio_summary || (professor.topic_tags?.length ? `Interests: ${professor.topic_tags.join(", ")}.` : "Explore this professor's public university profile.")}</p>}
              <ProfessorChip professor={professor} card />
              <Button variant="text" className="self-start text-sm" onClick={() => setEmailProfessor(professor)}><Mail size={15} aria-hidden="true" />Draft email</Button>
              <details className="text-[13px] text-muted"><summary className="min-h-11 cursor-pointer py-3">Courses and sources</summary>{professor.winter_courses?.length ? <p className="mb-2">Winter 2027: {professor.winter_courses.join(", ")}</p> : <p>No Winter courses listed yet.</p>}{professor.sources?.map((source, i) => <p key={i} className="mb-2"><a href={source.source_url} target="_blank" rel="noopener noreferrer" className="underline">{source.kind.replaceAll("_", " ")}</a> · Fetched {new Date(source.fetched_at).toLocaleDateString("en-US")}</p>)}</details>
            </div>
          </div></article>;
        })}</div>
        {!showAll && rows.length > shown.length && <Button variant="text" className="mt-5" onClick={() => setShowAll(true)}>Show all {rows.length} professors</Button>}
      </>}
    </section>
    {emailProfessor && <EmailDraft professor={emailProfessor} goal={goal} tags={emailTags} onClose={() => setEmailProfessor(null)} />}
  </PageFrame>;
}
