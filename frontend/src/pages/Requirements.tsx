import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useRemainingRequirements } from "../api/queries";
import type { AuditRequirement } from "../api/schemas";
import { Button } from "../components/ui/Button";
import { Empty } from "../components/ui/Empty";
import { ErrorState } from "../components/ui/ErrorState";
import { Loading } from "../components/ui/Loading";
import { PageFrame } from "../components/ui/PageFrame";
import { TagSquare } from "../components/ui/TagSquare";

/** A list shows at most this many items before "Show all" (frontend.md). */
const FIRST_PAGE = 6;

function credits(n: number): string {
  return `${n} ${n === 1 ? "credit" : "credits"} needed`;
}

function RequirementRow({ req }: { req: AuditRequirement }) {
  const options = req.options ?? [];
  return (
    <li className="flex flex-col gap-2 border-b border-line-soft px-6 py-5 last:border-b-0 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="flex min-w-0 flex-col gap-1.5">
        <p>
          <span className="font-semibold">{req.name}</span>
          <span className="text-muted"> · {req.group}</span>
        </p>
        {options.length > 0 ? (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            <span>{options.length === 1 ? "Fill it with" : "Fill it with one of"}</span>
            {options.map((code) => (
              <span
                key={code}
                className="inline-flex items-center gap-1.5 rounded-tag bg-field px-2 py-0.5 text-ink"
              >
                <TagSquare courseCode={code} />
                <span>{code}</span>
              </span>
            ))}
          </p>
        ) : (
          <p className="text-sm text-muted">Your audit lists no course options for this one.</p>
        )}
      </div>
      <p className="shrink-0 text-sm tabular-nums text-muted">{credits(req.credits_needed)}</p>
    </li>
  );
}

export function Requirements() {
  const navigate = useNavigate();
  const query = useRemainingRequirements();
  const [showAll, setShowAll] = useState(false);

  let content;
  if (query.isPending) {
    content = <Loading label="Loading requirements" />;
  } else if (query.isError) {
    content = (
      <ErrorState
        message="We couldn't load your requirements. Check your connection and try again."
        onRetry={() => void query.refetch()}
        retrying={query.isFetching}
      />
    );
  } else if (query.data.length === 0) {
    content = (
      <Empty
        message="Your audit shows nothing left to plan. Start over to load a different audit."
        actionLabel="Start over"
        onAction={() => navigate("/")}
      />
    );
  } else {
    const all = query.data;
    const shown = showAll ? all : all.slice(0, FIRST_PAGE);
    const total = all.reduce((sum, r) => sum + r.credits_needed, 0);
    content = (
      <section aria-labelledby="remaining-summary" className="flex flex-col gap-3">
        <p id="remaining-summary" className="text-sm tabular-nums text-muted">
          {all.length} {all.length === 1 ? "requirement" : "requirements"}, {total} credits in all
        </p>
        <ul className="rounded-card border border-line bg-surface">
          {shown.map((req) => (
            <RequirementRow key={req.id} req={req} />
          ))}
        </ul>
        {all.length > shown.length && (
          <Button variant="text" className="self-start" onClick={() => setShowAll(true)}>
            Show all {all.length}
          </Button>
        )}
      </section>
    );
  }

  return (
    <PageFrame
      title="What you still need"
      lead="Each requirement your audit shows as not met, with the classes that can fill it."
      footnote="Confirm with BYU-Idaho Academic Advising."
    >
      {content}
    </PageFrame>
  );
}
