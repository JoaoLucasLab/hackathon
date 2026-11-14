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

  it("shows only the confirmed week, read-only, with advising", async () => {
    backend(() => json(PLAN));
    renderApp("/plan");
    expect(await screen.findByRole("heading", { name: "Winter 2027 plan" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Week at a glance" })).toBeInTheDocument();
    expect(screen.getAllByTestId("calendar-event").length).toBeGreaterThan(0);
    const classes = screen.getByRole("list", { name: "Classes at a glance" });
    expect(within(classes).getAllByRole("listitem")).toHaveLength(PLAN.classes.length);
    // Each class names its section and professor.
    expect(within(classes).getByText("CSE 212-02")).toBeInTheDocument();
    expect(await within(classes).findByText("Taught by Ruth Okafor")).toBeInTheDocument();
    // Just the calendar: no class detail card and no "why" below it.
    expect(screen.queryByRole("list", { name: "Classes" })).not.toBeInTheDocument();
    expect(screen.queryByText("Why this schedule")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Confirm with BYU-Idaho Academic Advising\./).length).toBeGreaterThan(0);
    expect(screen.getByText(/This does not register you for classes/)).toBeInTheDocument();
    // Read-only: no way back to a list of options, no rule chips.
    expect(screen.queryByRole("button", { name: "All schedules" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Schedule options" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /rules/i })).not.toBeInTheDocument();
  });

  it("Start a new plan clears the plan and the chat, then opens an empty chat", async () => {
    let saved: Schedule | null = PLAN;
    const calls = fakeBackend({
      "GET /api/plan": () => (saved ? json(saved) : json({ detail: "No plan" }, 404)),
      "DELETE /api/chat/history": () => new Response(null, { status: 204 }),
      "DELETE /api/plan": () => {
        saved = null;
        return new Response(null, { status: 204 });
      },
      "GET /api/professors": () => json(professors),
    });
    const user = userEvent.setup();
    renderApp("/plan");
    await user.click(await screen.findByRole("button", { name: "Start a new plan" }));
    expect(await screen.findByLabelText(/what you want in your schedule/i)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([
      "/api/chat/history",
      "/api/plan",
    ]);
    await user.click(screen.getByRole("link", { name: "My plan" }));
    expect(await screen.findByText("No plan confirmed yet. Plan it in the chat.")).toBeInTheDocument();
  });

  it("sends the old Schedules link to My plan", async () => {
    backend(() => json({ detail: "No plan" }, 404));
    renderApp("/schedules");
    expect(await screen.findByRole("heading", { name: "My plan" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My plan" })).toHaveAttribute("aria-current", "page");
  });
});
