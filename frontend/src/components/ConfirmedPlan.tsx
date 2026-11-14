import type { Schedule } from "../api/schemas";
import { TERM_LABEL } from "../config";
import { ScheduleDetail, useClassRowData } from "./ScheduleDetail";
import { StartNewPlan } from "./StartNewPlan";
import { WeekGlance, courseColors } from "./WeekGlance";
import { plural } from "./scheduleFormat";

const ADVISING = "Confirm with BYU-Idaho Academic Advising.";

/**
 * AI-08: the confirmed plan, read-only, led by its colored week. The Plan tab shows
 * it in place of the chat, with the class details; My plan shows the week only.
 */
export function ConfirmedPlan({ schedule, calendarOnly = false }: { schedule: Schedule; calendarOnly?: boolean }) {
  const { reqNames, byId } = useClassRowData();
  const week = (
    <div className="rounded-card border border-line bg-surface p-4 md:p-5">
      <WeekGlance schedule={schedule} reqNames={reqNames} professors={byId} />
    </div>
  );

  if (calendarOnly) {
    return (
      <article aria-labelledby={`plan-${schedule.id}`} className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <h1 id={`plan-${schedule.id}`} className="font-serif text-[40px] font-normal leading-none md:text-[52px]">
            {TERM_LABEL} plan
          </h1>
          <p className="text-sm tabular-nums text-muted">
            {plural(schedule.total_credits, "credit")}, {plural(schedule.classes.length, "class")}
          </p>
        </div>
        <section aria-label="Week">{week}</section>
        <p className="text-sm font-medium">{schedule.advising_note ?? ADVISING}</p>
        <StartNewPlan />
      </article>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <ScheduleDetail
        schedule={schedule}
        heading={`${TERM_LABEL} plan`}
        colors={courseColors(schedule)}
        week={week}
      />
      <StartNewPlan />
    </div>
  );
}
