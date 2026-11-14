import { useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys, usePlan } from "../api/queries";
import { api, ApiError, unwrap } from "../api/client";
import { forgetPlanningSetup, hasPlanningSetup } from "../api/planningSetup";
import { usePlanningState, type Results } from "./PlanningState";

import { useRebuildSchedules } from "../api/queries";
import type { ChatEvent, ConstraintSet, DegreeAudit, Relaxation, Schedule } from "../api/schemas";
import { FloatingClassTickets } from "../components/FloatingClassTickets";
import { ChatPanel } from "../components/ChatPanel";
import { ConfirmedPlan } from "../components/ConfirmedPlan";
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
import { conversationalPlanner } from "../config";

const NO_RULES: ConstraintSet = {
  allow_waitlist: false,
  only_required: false,
  only_favorite_professors: false,
};

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
  const { results, setResults, busy } = usePlanningState();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isSchedules = location.pathname === "/schedules";
  const [asked, setAsked] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const rebuild = useRebuildSchedules();
  const built = useRef(false);
  // AI-08: the schedule stays in the chat; the page never moves to another tab.
  const oneAtATime = conversationalPlanner();
  const plan = usePlan(oneAtATime);
  // AI-08: once a plan is confirmed (and its reply has finished), the Plan tab shows
  // the plan and its week instead of the chat. "Start a new plan" brings the chat back.
  const confirmed = oneAtATime && !isSchedules && !busy && plan.data ? plan.data : null;

  function onEvent(event: ChatEvent) {
    if (event.type === "text" || event.type === "tool_call") setAsked(true);
    if (oneAtATime) return;
    if (event.type === "done" && built.current) {
      built.current = false;
      navigate("/schedules");
    }
    const found = resultsFrom(event);
    if (found) {
      built.current = true;
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
      title={confirmed || (selected && isSchedules) ? undefined : isSchedules ? (results?.schedules.length ? `${results.schedules.length === 3 ? "Three" : results.schedules.length} schedules fit` : "Your schedules") : "Plan a semester that fits your week"}
      lead={confirmed ? undefined : isSchedules ? (selected ? undefined : "Winter 2027, built from your degree audit and preferences.") : oneAtATime ? "Tell it what you want in plain words. It asks what it needs, then shows one Winter 2027 schedule at a time, each class with the requirement it fills." : "Tell it what you want in plain words. Compare Winter 2027 schedules built from your degree audit, each class with the requirement it fills."}
      home={!isSchedules && !confirmed}
      footnote={<>{isSchedules && seats && <>{seats} </>}{confirmed && <>This does not register you for classes. </>}Confirm with BYU-Idaho Academic Advising.</>}
    >
      {confirmed && <ConfirmedPlan schedule={confirmed} />}
      {!isSchedules && !confirmed && <FloatingClassTickets audit={queryClient.getQueryData<DegreeAudit>(queryKeys.audit)} />}
      <div hidden={isSchedules || Boolean(confirmed)} className="mx-auto w-full max-w-[680px] md:mt-2">
        <ChatPanel onEvent={onEvent}
          beforeSend={async (signal) => {
            if (queryClient.getQueryData(queryKeys.audit)) return true;
            if (hasPlanningSetup()) {
              try {
                // Read the existing session; never create one or reload a sample audit here.
                const requirements = unwrap(await api.GET("/api/requirements/remaining", { signal }));
                if (signal.aborted) return false;
                queryClient.setQueryData(queryKeys.remaining, requirements);
                return true;
              } catch (error) {
                if (signal.aborted) return false;
                if (!(error instanceof ApiError) || ![401, 403, 404].includes(error.status)) {
                  throw error;
                }
                forgetPlanningSetup();
              }
            }
            navigate("/consent");
            return false;
          }} />
        {!oneAtATime && !results && asked && <p className="mt-4 text-sm text-muted">Schedules appear when the assistant builds them.</p>}
      </div>
      {isSchedules && selected && <ScheduleDetail schedule={selected} onBack={() => setSelectedId(null)} />}
      {isSchedules && !selected && (results ? (
        <section aria-label="Schedules" className="flex flex-col gap-8">
          <ConstraintChips constraints={results.constraints} onChange={onRulesChange} disabled={rebuild.isPending} />
          {schedulesBlock}
          <Link to="/" className="self-start text-sm text-muted underline underline-offset-4">Refine your plan</Link>
        </section>
      ) : <Empty message="No schedules yet. Tell us how you want your week to look to build your first options." actionLabel="Plan my schedule" onAction={() => navigate("/")} />)}
    </PageFrame>
  );
}
