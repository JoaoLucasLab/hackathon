import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Schedule } from "../api/schemas";
import calendarSchedule from "../test/data/calendar_schedule.json";
import { WeekCalendar, calendarEvents, rowLine } from "./WeekCalendar";

const schedule = calendarSchedule as unknown as Schedule;

function day(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

function event(dayName: string, code: string): HTMLElement {
  return within(day(dayName)).getByRole("listitem", { name: new RegExp(`^${code}`) });
}

describe("WeekCalendar", () => {
  it("shows Monday to Saturday", () => {
    render(<WeekCalendar schedule={schedule} />);
    for (const name of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]) {
      expect(day(name)).toBeInTheDocument();
    }
    expect(screen.queryByRole("region", { name: "Sunday" })).not.toBeInTheDocument();
  });

  it("puts a TR 12:45-01:45PM class on Tuesday and Thursday in the right rows", () => {
    render(<WeekCalendar schedule={schedule} />);
    // The earliest class starts at 12:45, so the grid starts at 12:00 (row 1).
    // Rows are 15 minutes: 12:45 is line 4, 1:45 PM is line 8.
    expect(rowLine(12 * 60 + 45, 12 * 60)).toBe(4);
    for (const name of ["Tuesday", "Thursday"]) {
      const box = event(name, "CSE 212-02");
      expect(box).toHaveAccessibleName("CSE 212-02, 12:45 PM to 1:45 PM");
      expect(box.style.gridRow).toBe("4 / 8");
    }
    for (const name of ["Monday", "Wednesday", "Friday", "Saturday"]) {
      expect(
        within(day(name)).queryByRole("listitem", { name: /^CSE 212-02/ }),
      ).not.toBeInTheDocument();
    }
  });

  it("labels First and Second Block with text and a pattern, and keeps both readable at the same time", () => {
    render(<WeekCalendar schedule={schedule} />);
    const first = event("Monday", "WDD 231-02");
    const second = event("Monday", "WDD 231-03");
    expect(first).toHaveAccessibleName(/First Block$/);
    expect(second).toHaveAccessibleName(/Second Block$/);
    expect(within(first).getByText("First Block")).toBeInTheDocument();
    expect(within(second).getByText("Second Block")).toBeInTheDocument();
    expect(first.querySelector(".sw-first")).not.toBeNull();
    expect(second.querySelector(".sw-second")).not.toBeNull();
    // Same rows, side by side in separate lanes instead of on top of each other.
    expect(first.style.gridRow).toBe(second.style.gridRow);
    expect(first.style.gridColumn).not.toBe(second.style.gridColumn);
  });

  it('lists online classes with no meeting time under the calendar as "Online, no set time"', () => {
    render(<WeekCalendar schedule={schedule} />);
    const list = screen.getByRole("list", { name: "Online, no set time" });
    expect(within(list).getByText("MATH 113-04")).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: /^MATH 113-04/ })).not.toBeInTheDocument();
  });

  it("gives non-overlapping classes the full column", () => {
    const events = calendarEvents(schedule);
    const tuesday = events.filter((e) => e.day === "T");
    expect(tuesday.every((e) => e.lanes === 1)).toBe(true);
  });
});
