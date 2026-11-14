import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ChatEvent, ConstraintSet } from "../api/schemas";
import buildResult from "../test/data/build_schedules.json";
import { fakeBackend, json, renderApp } from "../test/utils";

type Event = Partial<ChatEvent> & { type: ChatEvent["type"] };

/** A streamed `text/event-stream` body. Chunks deliberately split events in two. */
function sse(events: Event[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const mid = Math.floor(body.length / 2);
  const chunks = [body.slice(0, mid), body.slice(mid)];
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

const MESSAGE = "No morning classes, 12 to 15 credits, no Fridays";

const happyStream: Event[] = [
  { type: "text", text: "Let me check." },
  { type: "tool_call", tool: "build_schedules", data: { constraints: buildResult.constraints } },
  { type: "tool_result", tool: "build_schedules", data: buildResult as Record<string, unknown> },
  { type: "text", text: "Here are three schedules " },
  { type: "text", text: "that fit your rules." },
  { type: "done" },
];

async function ask(message = MESSAGE) {
  const user = userEvent.setup();
  renderApp("/planner");
  await user.type(screen.getByLabelText(/what you want in your schedule/i), message);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

describe("ChatPanel on the planner", () => {
  it("streams the reply and shows 3 schedule cards with course, section, days, times and credits", async () => {
    const calls = fakeBackend({ "POST /api/chat": () => sse(happyStream) });
    await ask();

    const reply = await screen.findByText(/Here are three schedules that fit your rules\./);
    // Text from the step after a tool starts a new paragraph instead of running together.
    expect(reply.textContent).toBe("Let me check.\n\nHere are three schedules that fit your rules.");
    expect(calls.find((c) => c.path === "/api/chat")?.body).toEqual({ message: MESSAGE });

    const cards = within(screen.getByRole("list", { name: "Schedule options" })).getAllByRole(
      "article",
    );
    expect(cards).toHaveLength(3);
    const first = cards[0] as HTMLElement;
    expect(within(first).getByText("Option 1")).toBeInTheDocument();
    expect(within(first).getByText("CSE 212-02")).toBeInTheDocument(); // course + section
    expect(within(first).getAllByText(/\d+ credits?$/).length).toBeGreaterThan(0); // credits
    expect(within(first).getAllByText(/(Mon|Tue|Wed|Thu|Fri|Sat).* (AM|PM) to /).length).toBeGreaterThan(0);

    expect(screen.getByText(/Confirm with BYU-Idaho Academic Advising\./)).toBeInTheDocument();
    expect(screen.getByText(/Seats as of/)).toBeInTheDocument();
  });

  it("shows the three rules as chips", async () => {
    fakeBackend({ "POST /api/chat": () => sse(happyStream) });
    await ask();
    const chips = within(await screen.findByRole("list", { name: "Your rules" })).getAllByRole(
      "listitem",
    );
    expect(chips.map((c) => c.textContent)).toEqual([
      "No class before 11:30 AM",
      "12 to 15 credits",
      "Fridays off",
    ]);
  });

  it("removing a chip saves the rules and rebuilds the schedules without asking Claude", async () => {
    const rebuilt = {
      ...buildResult,
      schedules: buildResult.schedules.slice(0, 2),
    };
    const calls = fakeBackend({
      "POST /api/chat": () => sse(happyStream),
      "PUT /api/constraints": async (req) => json(await req.json()),
      "POST /api/schedules/build": () => json(rebuilt),
    });
    const user = await ask();
    await user.click(await screen.findByRole("button", { name: "Remove rule: Fridays off" }));

    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Schedule options" })).getAllByRole("article"),
      ).toHaveLength(2),
    );
    const put = calls.find((c) => c.method === "PUT")?.body as ConstraintSet;
    expect(put.days_off).toEqual([]);
    expect(put.earliest_start).toBe("11:30:00");
    const build = calls.find((c) => c.path === "/api/schedules/build")?.body as {
      constraints: ConstraintSet;
    };
    expect(build.constraints.days_off).toEqual([]);
    expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Remove rule: Fridays off" })).toBeNull();
  });

  it("shows a status line while a tool runs, never the raw tool name", async () => {
    fakeBackend({
      "POST /api/chat": () =>
        sse([{ type: "tool_call", tool: "search_sections", data: { course_codes: ["CSE 212"] } }]),
    });
    await ask("Is CSE 212 offered?");
    expect(await screen.findByText("Looking up sections")).toBeInTheDocument();
    expect(screen.queryByText(/search_sections/)).toBeNull();
  });

  it("shows the error message from the stream", async () => {
    fakeBackend({
      "POST /api/chat": () =>
        sse([
          { type: "error", text: "The assistant is unavailable right now. Please try again in a minute." },
          { type: "done" },
        ]),
    });
    await ask();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The assistant is unavailable right now.",
    );
  });

  it("shows a clear message when the backend cannot be reached", async () => {
    fakeBackend({ "POST /api/chat": () => new Response("down", { status: 503 }) });
    await ask();
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't reach the assistant.");
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("a suggestion fills the prompt but does not send it", async () => {
    const calls = fakeBackend({});
    const user = userEvent.setup();
    renderApp("/planner");
    await user.click(screen.getByRole("button", { name: "Fridays off" }));
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue(
      "No classes on Fridays",
    );
    expect(calls).toHaveLength(0);
  });

  it("every control is reachable with Tab", async () => {
    fakeBackend({});
    const user = userEvent.setup();
    renderApp("/planner");
    await user.type(screen.getByLabelText(/what you want in your schedule/i), "hi");
    const reached = new Set<Element | null>();
    for (let i = 0; i < 15; i++) {
      await user.tab();
      reached.add(document.activeElement);
    }
    for (const button of screen.getAllByRole("button")) expect(reached).toContain(button);
  });
});
