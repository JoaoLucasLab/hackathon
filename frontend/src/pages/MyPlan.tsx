import { useNavigate } from "react-router-dom";

import { usePlan } from "../api/queries";
import { ScheduleDetail } from "../components/ScheduleDetail";
import { Empty } from "../components/ui/Empty";
import { ErrorState } from "../components/ui/ErrorState";
import { Loading } from "../components/ui/Loading";
import { PageFrame } from "../components/ui/PageFrame";
import { formatAsOf } from "../components/scheduleFormat";
import { TERM_LABEL } from "../config";

/**
 * AI-08: the schedule the student confirmed in the chat, read-only. It changes only
 * when the student confirms another one in the chat.
 */
export function MyPlan() {
  const navigate = useNavigate();
  const plan = usePlan();
  const seats = plan.data
    ? plan.data.classes.map((c) => c.section.seats.as_of).sort()[0]
    : undefined;

  let body;
  if (plan.isPending) {
    body = <Loading label="Loading your plan" />;
  } else if (plan.isError) {
    body = (
      <ErrorState
        message="We couldn't load your plan. Check your connection and try again."
        onRetry={() => void plan.refetch()}
        retrying={plan.isFetching}
      />
    );
  } else if (plan.data === null) {
    body = (
      <Empty
        message="No plan confirmed yet. Plan it in the chat."
        actionLabel="Plan my schedule"
        onAction={() => navigate("/")}
      />
    );
  } else {
    body = <ScheduleDetail schedule={plan.data} heading={`${TERM_LABEL} plan`} />;
  }

  return (
    <PageFrame
      title={plan.data ? undefined : "My plan"}
      lead={
        plan.data
          ? undefined
          : "The schedule you confirm in the chat. Confirming it does not register you for classes."
      }
      footnote={
        <>
          {seats && <>Seats as of {formatAsOf(seats)}. </>}
          This does not register you for classes. Confirm with BYU-Idaho Academic Advising.
        </>
      }
    >
      {body}
    </PageFrame>
  );
}
