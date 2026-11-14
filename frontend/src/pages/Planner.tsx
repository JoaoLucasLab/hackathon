import { useState } from "react";

import { useRebuildSchedules } from "../api/queries";
import type { ChatEvent, ConstraintSet, Relaxation, Schedule } from "../api/schemas";
import { ChatPanel } from "../components/ChatPanel";
import { ConstraintChips } from "../components/ConstraintChips";
import { ScheduleCard } from "../components/ScheduleCard";
import { ScheduleDetail } from "../components/ScheduleDetail";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Empty } from "../components/ui/Empty";
import { ErrorState } from "../components/ui/ErrorState";
import { Loading } from "../components/ui/Loading";
import { PageFrame } from "../components/ui/PageFrame";
import { plural } from "../components/scheduleFormat";

const NO_RULES: ConstraintSet = {
  allow_waitlist: false,
  only_required: false,
  only_favorite_professors: false,
};

interface Results {
  constraints: ConstraintSet;
  schedules: Schedule[];
  relaxation?: Relaxation | null;
}

/** The `build_schedules` tool result carries the rules it used and the schedules. */
function resultsFrom(event: ChatEvent): Results | null {
  if (event.type !== "tool_result" || event.tool !== "build_schedules" || !event.data) return null;
  const data = event.data as {
    constraints?: ConstraintSet;
    schedules?: Schedule[];
    relaxation?: Relaxation | null;
  };
  if (!data.constraints || !data.schedules) return null;
  return {
    constraints: data.constraints,
    schedules: data.schedules,
    relaxation: data.relaxation ?? null,
  };
}

/** "Seats as of Nov 13, 3:00 PM": the oldest seat count shown. */
function seatsAsOf(schedules: Schedule[]): string | null {
  const times = schedules.flatMap((s) => s.classes.map((c) => c.section.seats.as_of)).sort();
  if (times.length === 0) return null;
  const when = new Date(times[0] as string).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return `Seats as of ${when}.`;
}

export function Planner() {
  const [results, setResults] = useState<Results | null>(null);
  const [asked, setAsked] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const rebuild = useRebuildSchedules();

  function onEvent(event: ChatEvent) {
    if (event.type === "text" || event.type === "tool_call") setAsked(true);
    const found = resultsFrom(event);
    if (found) {
      setResults(found);
      setSelectedId(null);
    }
  }

  function onRulesChange(next: ConstraintSet) {
    setResults((r) => (r ? { ...r, constraints: next } : r));
    rebuild.mutate(next, {
      onSuccess: (response) =>
        setResults({
          constraints: next,
          schedules: response.schedules,
          relaxation: response.relaxation ?? null,
        }),
    });
  }

  let schedulesBlock = null;
  if (rebuild.isPending) {
    schedulesBlock = <Loading label="Rebuilding schedules" />;
  } else if (rebuild.isError) {
    schedulesBlock = (
      <ErrorState
        message="We couldn't rebuild your schedules. Check your connection and try again."
        onRetry={() => results && onRulesChange(results.constraints)}
        retrying={rebuild.isPending}
      />
    );
  } else if (results && results.schedules.length === 0 && results.relaxation) {
    const hint = results.relaxation;
    schedulesBlock = (
      <Card className="flex flex-col items-start gap-4">
        <p>
          No schedule fits all of your rules. If you {hint.change},{" "}
          {plural(hint.schedules_available, "schedule")} would fit.
        </p>
        <Button variant="primary" onClick={() => onRulesChange(hint.patch)}>
          Apply this change
        </Button>
      </Card>
    );
  } else if (results && results.schedules.length === 0) {
    schedulesBlock = (
      <Empty
        message="No schedule fits all of your rules. Remove a rule to see more options."
        actionLabel="Clear all rules"
        onAction={() => onRulesChange(NO_RULES)}
      />
    );
  } else if (results) {
    schedulesBlock = (
      <ol aria-label="Schedule options" className="flex flex-col gap-5">
        {results.schedules.map((s) => (
          <li key={s.id}>
            <ScheduleCard schedule={s} onSelect={(picked) => setSelectedId(picked.id)} />
          </li>
        ))}
      </ol>
    );
  }

  const seats = results ? seatsAsOf(results.schedules) : null;
  const selected = results?.schedules.find((s) => s.id === selectedId) ?? null;

  return (
    <PageFrame
      title="Plan a semester that fits your week"
      lead="Tell the assistant what you want. It builds schedules from your remaining requirements."
      footnote={
        <>
          {seats && <>{seats} </>}
          Confirm with BYU-Idaho Academic Advising.
        </>
      }
    >
      {/* Hidden, not unmounted, while one schedule is open, so the chat keeps its history. */}
      {/* No display class here: Tailwind's `.flex` would beat the `hidden` attribute. */}
      <div hidden={selected !== null}>
        <ChatPanel onEvent={onEvent} />
      </div>
      {selected && <ScheduleDetail schedule={selected} onBack={() => setSelectedId(null)} />}
      {results && !selected && (
        <section aria-label="Schedules" className="flex flex-col gap-4">
          <ConstraintChips
            constraints={results.constraints}
            onChange={onRulesChange}
            disabled={rebuild.isPending}
          />
          {schedulesBlock}
        </section>
      )}
      {!results && asked && (
        <p className="text-sm text-muted">Schedules appear here when the assistant builds them.</p>
      )}
    </PageFrame>
  );
}
