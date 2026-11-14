import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import audit from "../../../fixtures/audit.json";
import professors from "../../../fixtures/professors.json";
import type { Schedule } from "../api/schemas";
import buildResult from "../test/data/build_schedules.json";
import { fakeBackend, json, renderApp, type Handler } from "../test/utils";

const PLAN = buildResult.schedules[0] as unknown as Schedule;

function backend(plan: Handler) {
  return fakeBackend({
    "GET /api/plan": plan,
    "GET /api/professors": () => json(professors),
    "GET /api/requirements/remaining": () =>
      json(audit.requirements.filter((r) => r.status === "not_met")),
  });
}

beforeEach(() => {
  vi.stubEnv("VITE_FEATURE_CONVERSATIONAL_PLANNER", "true");
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("My plan", () => {
  it("shows a loading state while the plan loads", async () => {
    backend(() => new Promise<Response>(() => {}));
    renderApp("/plan");
    expect(await screen.findByRole("status", { name: "Loading your plan" })).toBeInTheDocument();
  });

  it("shows the empty state when no plan is confirmed, with a way back to the chat", async () => {
    backend(() => json({ detail: "No plan confirmed yet" }, 404));
    const user = userEvent.setup();
    renderApp("/plan");
    expect(await screen.findByText("No plan confirmed yet. Plan it in the chat.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Plan my schedule" }));
    expect(screen.getByLabelText(/what you want in your schedule/i)).toBeInTheDocument();
  });

  it("shows an error state that retries", async () => {
    let fail = true;
    backend(() => (fail ? json({}, 500) : json(PLAN)));
    const user = userEvent.setup();
    renderApp("/plan");
    expect(await screen.findByText(/We couldn't load your plan/)).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Winter 2027 plan" })).toBeInTheDocument();
  });

  it("shows the confirmed schedule read-only: calendar, classes, professors, advising", async () => {
    backend(() => json(PLAN));
    renderApp("/plan");
    expect(await screen.findByRole("heading", { name: "Winter 2027 plan" })).toBeInTheDocument();
    expect(screen.getAllByTestId("calendar-event").length).toBeGreaterThan(0);
    const classes = screen.getByRole("list", { name: "Classes" });
    expect(within(classes).getAllByRole("listitem").length).toBeGreaterThanOrEqual(PLAN.classes.length);
    expect(await screen.findAllByText("See on Rate My Professors")).not.toHaveLength(0);
    expect(screen.getAllByText(/Confirm with BYU-Idaho Academic Advising\./).length).toBeGreaterThan(0);
    expect(screen.getByText(/This does not register you for classes/)).toBeInTheDocument();
    // Read-only: no way back to a list of options, no rule chips.
    expect(screen.queryByRole("button", { name: "All schedules" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Schedule options" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /rules/i })).not.toBeInTheDocument();
  });

  it("sends the old Schedules link to My plan", async () => {
    backend(() => json({ detail: "No plan" }, 404));
    renderApp("/schedules");
    expect(await screen.findByRole("heading", { name: "My plan" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My plan" })).toHaveAttribute("aria-current", "page");
  });
});
