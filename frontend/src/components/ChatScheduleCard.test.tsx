import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import audit from "../../../fixtures/audit.json";
import professors from "../../../fixtures/professors.json";
import type { ChatEvent, Schedule } from "../api/schemas";
import buildResult from "../test/data/build_schedules.json";
import { fakeBackend, json, renderApp, type Handler } from "../test/utils";
import { dayLetters, summaryLine } from "./ChatScheduleCard";

type Event = Partial<ChatEvent> & { type: ChatEvent["type"] };

function sse(events: Event[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

const FIRST = buildResult.schedules[0] as unknown as Schedule;
// Option 2: the same schedule without CIT 225, so it is a different one.
const SECOND: Schedule = {
  ...FIRST,
  id: "sch-second",
  total_credits: 12,
  classes: FIRST.classes.filter((c) => c.section.course_code !== "CIT 225"),
};
const ASK = "Does this schedule work for you? Confirm with BYU-Idaho Academic Advising.";

function built(schedule: Schedule, option: number): Event[] {
  return [
    { type: "tool_call", tool: "build_schedules", data: {} },
    {
      type: "tool_result",
      tool: "build_schedules",
      data: { constraints: buildResult.constraints, schedules: [schedule], option, excluded: [] },
    },
    { type: "text", text: ASK },
    { type: "done" },
  ];
}

/** The backend for the loop: each chat message gets the next stream. */
function loopBackend(streams: Event[][], extra: Record<string, Handler> = {}) {
  let plan: Schedule | null = null;
  const queue = [...streams];
  const calls = fakeBackend({
    "POST /api/chat": async (req) => {
      const { message } = (await req.json()) as { message: string };
      if (message === "This works") plan = SECOND;
      return sse(queue.shift() ?? [{ type: "done" }]);
    },
    "GET /api/plan": () => (plan ? json(plan) : json({ detail: "No plan" }, 404)),
    "GET /api/professors": () => json(professors),
    "GET /api/requirements/remaining": () =>
      json(audit.requirements.filter((r) => r.status === "not_met")),
    ...extra,
  });
  return calls;
}

async function send(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText(/what you want in your schedule/i), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

beforeEach(() => {
  vi.stubEnv("VITE_FEATURE_CONVERSATIONAL_PLANNER", "true");
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("summary line", () => {
  it("names the option, credits, days and whether it was chosen", () => {
    expect(dayLetters(FIRST)).toBe("MTWRF");
    expect(summaryLine(FIRST, 1, false)).toBe("Option 1: 15 credits, MTWRF, not chosen");
    expect(summaryLine(SECOND, 2, true)).toBe("Option 2: 12 credits, MTWRF, confirmed");
  });

  it("says online only when no class has a set time", () => {
    const online: Schedule = {
      ...FIRST,
      classes: FIRST.classes.map((c) => ({ ...c, section: { ...c.section, meetings: [] } })),
    };
    expect(dayLetters(online)).toBe("online only");
  });
});

describe("one schedule in the chat", () => {
  it("shows exactly one card in the reply, with the calendar, requirements, professors, seats and advising", async () => {
    loopBackend([built(FIRST, 1)]);
    const user = userEvent.setup();
    const { queryClient } = renderApp("/planner");
    queryClient.setQueryData(["audit"], { loaded: true });
    await send(user, "yes");

    const card = await screen.findByRole("article", { name: "Option 1" });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(within(card).getAllByTestId("calendar-event").length).toBeGreaterThan(0);
    // The week at a glance: span in the header, a free day, one row per class with seats.
    expect(within(card).getByText("Mon to Fri · 10:15 AM–1:45 PM")).toBeInTheDocument();
    const glance = within(card).getByRole("list", { name: "Classes at a glance" });
    expect(within(glance).getAllByRole("listitem")).toHaveLength(FIRST.classes.length);
    expect(within(glance).getAllByText(/^\d+ seats? open$/)).toHaveLength(FIRST.classes.length);
    expect(within(card).getByText(/^Seats as of /)).toBeInTheDocument();
    expect(within(card).getByRole("list", { name: "Checks" })).toHaveTextContent("No conflicts");
    // The full details sit behind "Class details".
    await user.click(within(card).getByRole("button", { name: "Class details" }));
    // Each class says which requirement it fills.
    const fills = await within(card).findAllByText(/^Fills:/);
    expect(fills).toHaveLength(FIRST.classes.length);
    expect(fills[0]?.parentElement).toHaveTextContent("Fills: Programming with Data Structures");
    expect(await within(card).findAllByRole("button", { name: /^Star / })).not.toHaveLength(0);
    expect(within(card).getAllByText("See on Rate My Professors").length).toBeGreaterThan(0);
    expect(within(card).getByText("Confirm with BYU-Idaho Academic Advising.")).toBeInTheDocument();
    expect(screen.getByText(ASK)).toBeInTheDocument();
    // The page stays on the chat: no move to the old 3-card screen.
    expect(screen.queryByRole("list", { name: "Schedule options" })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/what you want in your schedule/i)).toBeInTheDocument();
  });

  it("offers This works and Change something; Change something puts the cursor in the message box", async () => {
    loopBackend([built(FIRST, 1)]);
    const user = userEvent.setup();
    const { queryClient } = renderApp("/planner");
    queryClient.setQueryData(["audit"], { loaded: true });
    await send(user, "yes");

    const replies = await screen.findByRole("list", { name: "Does this schedule work?" });
    expect(within(replies).getByRole("button", { name: "This works" })).toBeInTheDocument();
    await user.click(within(replies).getByRole("button", { name: "Change something" }));
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveFocus();
  });

  it("collapses the older card to one line, expands it again, and swaps the chat for the confirmed plan", async () => {
    const calls = loopBackend([
      built(FIRST, 1),
      built(SECOND, 2),
      [
        { type: "tool_call", tool: "confirm_schedule", data: { schedule_id: SECOND.id } },
        { type: "tool_result", tool: "confirm_schedule", data: { confirmed: true } },
        {
          type: "text",
          text: "Saved as your Winter 2027 plan. This does not register you for classes. Confirm with BYU-Idaho Academic Advising.",
        },
        { type: "done" },
      ],
    ]);
    const user = userEvent.setup();
    const { queryClient } = renderApp("/planner");
    queryClient.setQueryData(["audit"], { loaded: true });
    await send(user, "yes");
    await screen.findByRole("article", { name: "Option 1" });
    await send(user, "no classes on Friday");

    await screen.findByRole("heading", { name: "Option 2" });
    const older = screen.getByRole("button", { name: /Option 1: 15 credits, MTWRF, not chosen/ });
    expect(older).toHaveAttribute("aria-expanded", "false");
    older.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Option 1" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "This works" }));

    // Once saved, the Plan tab shows the plan led by its week, and hides the chat.
    expect(await screen.findByRole("heading", { name: "Winter 2027 plan" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Week at a glance" })).toBeVisible();
    expect(screen.getByLabelText(/what you want in your schedule/i)).not.toBeVisible();
    expect(screen.queryByText(/Saved as your Winter 2027 plan/)).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Start a new plan" })).toBeInTheDocument();

    // My plan shows the same week.
    await user.click(screen.getByRole("link", { name: "My plan" }));
    expect(await screen.findByRole("heading", { name: "Winter 2027 plan" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Week at a glance" })).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/chat").map((c) => c.body)).toEqual([
      { message: "yes" },
      { message: "no classes on Friday" },
      { message: "This works" },
    ]);
  });

  it("Start a new plan clears the conversation and the plan on the server and opens an empty chat", async () => {
    const calls = loopBackend([built(FIRST, 1)], {
      "DELETE /api/chat/history": () => new Response(null, { status: 204 }),
      "DELETE /api/plan": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    const { queryClient } = renderApp("/planner");
    queryClient.setQueryData(["audit"], { loaded: true });
    await send(user, "yes");
    await screen.findByRole("article", { name: "Option 1" });

    await user.click(screen.getByRole("button", { name: "Start a new plan" }));
    await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
    expect(screen.queryByText("yes")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Suggestions" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/chat/history" && c.method === "DELETE")).toBe(true);
    expect(calls.some((c) => c.path === "/api/plan" && c.method === "DELETE")).toBe(true);
  });

  it("shows the no-fit hint with Apply this change, and no card", async () => {
    loopBackend([
      [
        {
          type: "tool_result",
          tool: "build_schedules",
          data: {
            constraints: buildResult.constraints,
            schedules: [],
            excluded: [],
            relaxation: {
              constraint: "latest_end",
              change: "allow classes until 12:30 instead of 10:00",
              schedules_available: 1,
              patch: buildResult.constraints,
            },
          },
        },
        { type: "text", text: "No schedule fits all of your rules." },
        { type: "done", data: { quick_replies: ["Apply this change"] } },
      ],
    ]);
    const user = userEvent.setup();
    const { queryClient } = renderApp("/planner");
    queryClient.setQueryData(["audit"], { loaded: true });
    await send(user, "yes");

    expect(
      await screen.findByText(/If you allow classes until 12:30 instead of 10:00, 1 schedule would fit\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply this change" })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "This works" })).not.toBeInTheDocument();
  });

  it("restores the conversation and its card after a reload", async () => {
    const calls = loopBackend([], {
      "GET /api/chat/history": () =>
        json({
          turns: [
            { role: "student", text: "Build it" },
            { role: "assistant", text: ASK, schedule: FIRST, option: 1, quick_replies: [] },
          ],
        }),
    });
    renderApp("/planner");

    expect(await screen.findByText("Build it")).toBeInTheDocument();
    expect(await screen.findByRole("article", { name: "Option 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "This works" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/chat")).toBe(false);
  });

  it("calls the Schedules tab My plan", async () => {
    loopBackend([]);
    const user = userEvent.setup();
    renderApp("/planner");
    expect(screen.queryByRole("link", { name: "Schedules" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "My plan" }));
    expect(await screen.findByText("No plan confirmed yet. Plan it in the chat.")).toBeInTheDocument();
  });
});
