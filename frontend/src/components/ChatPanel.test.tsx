import { act, screen, waitFor, within } from "@testing-library/react";
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
  const { queryClient } = renderApp("/planner");
  queryClient.setQueryData(["audit"], { loaded: true });
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

    const cards = within(await screen.findByRole("list", { name: "Schedule options" })).getAllByRole(
      "article",
    );
    expect(cards).toHaveLength(3);
    const first = cards[0] as HTMLElement;
    await userEvent.click(within(first).getByText("Preview classes"));
    expect(within(first).getByText("Option 1")).toBeInTheDocument();
    expect(within(first).getByText("CSE 212-02")).toBeInTheDocument(); // course + section
    expect(within(first).getAllByText(/\d+ credits?$/).length).toBeGreaterThan(0); // credits
    expect(within(first).getAllByText(/(Mon|Tue|Wed|Thu|Fri|Sat).* (AM|PM) to /).length).toBeGreaterThan(0);

    expect(screen.getByText(/Confirm with BYU-Idaho Academic Advising\./)).toBeInTheDocument();
    expect(screen.getByText(/Seats as of/)).toBeInTheDocument();
  });

  it("keeps schedules when switching through Professors, and clears them after deleting data", async () => {
    fakeBackend({
      "POST /api/chat": () => sse(happyStream),
      "GET /api/professors": () => json([]),
      "DELETE /api/me": () => new Response(null, { status: 204 }),
    });
    const user = await ask();
    await screen.findByRole("list", { name: "Schedule options" });
    await user.click(screen.getByRole("link", { name: "Professors" }));
    await screen.findByText(/No professors match this topic yet/);
    await user.click(screen.getByRole("link", { name: "Schedules" }));
    expect(screen.getByRole("list", { name: "Schedule options" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete my data" }));
    await screen.findByRole("heading", { name: "Before you start" });
    await user.click(screen.getByRole("link", { name: "Schedules" }));
    expect(screen.getByText(/No schedules yet/)).toBeInTheDocument();
  });

  it("keeps the conversation and unsent draft through Professors and Schedules", async () => {
    fakeBackend({
      "POST /api/chat": () => sse([{ type: "text", text: "Which days would you prefer?" }, { type: "done" }]),
      "GET /api/professors": () => json([]),
    });
    const user = await ask("Help me plan");
    await screen.findByText("Which days would you prefer?");
    await user.type(screen.getByLabelText(/what you want in your schedule/i), "Keep Thursday free");
    await user.click(screen.getByRole("link", { name: "Professors" }));
    await screen.findByText(/No professors match this topic yet/);
    await user.click(screen.getByRole("link", { name: "Schedules" }));
    await user.click(screen.getByRole("link", { name: "Plan" }));
    expect(screen.getByText("Help me plan")).toBeInTheDocument();
    expect(screen.getByText("Which days would you prefer?")).toBeInTheDocument();
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("Keep Thursday free");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Keep Thursday free")).toBeInTheDocument();
    expect(screen.getAllByText("Which days would you prefer?")).toHaveLength(2);
  });

  it("continues a streamed reply across tab changes and prevents duplicate sends", async () => {
    let output!: ReadableStreamDefaultController<Uint8Array>;
    const encoder = new TextEncoder();
    const calls = fakeBackend({
      "POST /api/chat": () => new Response(new ReadableStream<Uint8Array>({ start(controller) { output = controller; } })),
      "GET /api/professors": () => json([]),
    });
    const user = await ask("Keep my mornings free");
    await waitFor(() => expect(output).toBeDefined());
    await act(async () => { output.enqueue(encoder.encode('data: {"type":"text","text":"Looking at "}\n\n')); });
    await screen.findByText("Looking at");
    await user.click(screen.getByRole("link", { name: "Professors" }));
    await screen.findByText(/No professors match this topic yet/);
    await user.click(screen.getByRole("link", { name: "Plan" }));
    expect(screen.getByRole("button", { name: "Sending" })).toBeDisabled();
    await user.type(screen.getByLabelText(/what you want in your schedule/i), "Next question{enter}");
    expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1);
    await act(async () => {
      output.enqueue(encoder.encode('data: {"type":"text","text":"your options."}\n\ndata: {"type":"done"}\n\n'));
      output.close();
    });
    expect(await screen.findByText("Looking at your options.")).toBeInTheDocument();
    expect(screen.getByText("Keep my mornings free")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  });

  it("clears conversation, draft, and setup marker when data is deleted", async () => {
    localStorage.setItem("planning-setup-complete", "true");
    fakeBackend({
      "POST /api/chat": () => sse([{ type: "text", text: "Your previous answer." }, { type: "done" }]),
      "DELETE /api/me": () => new Response(null, { status: 204 }),
    });
    const user = await ask("My previous question");
    await screen.findByText("Your previous answer.");
    await user.type(screen.getByLabelText(/what you want in your schedule/i), "Unsent draft");
    await user.click(screen.getByRole("button", { name: "Delete my data" }));
    await screen.findByRole("heading", { name: "Before you start" });
    expect(localStorage.getItem("planning-setup-complete")).toBeNull();
    await user.click(screen.getByRole("link", { name: "Plan" }));
    expect(screen.queryByText("Your previous answer.")).not.toBeInTheDocument();
    expect(screen.queryByText("My previous question")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("");
  });

  it("aborts an active reply on deletion and ignores late schedule results", async () => {
    let output!: ReadableStreamDefaultController<Uint8Array>;
    let requestSignal!: AbortSignal;
    fakeBackend({
      "POST /api/chat": (request) => {
        requestSignal = request.signal;
        return new Response(new ReadableStream<Uint8Array>({ start(controller) { output = controller; } }));
      },
      "DELETE /api/me": () => new Response(null, { status: 204 }),
    });
    const user = await ask("A schedule please");
    await waitFor(() => expect(output).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Delete my data" }));
    await screen.findByRole("heading", { name: "Before you start" });
    expect(requestSignal.aborted).toBe(true);
    await act(async () => {
      const events = [{ type: "tool_result", tool: "build_schedules", data: buildResult }, { type: "done" }];
      output.enqueue(new TextEncoder().encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")));
      output.close();
    });
    expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Schedules" }));
    expect(screen.getByText(/No schedules yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Plan" }));
    expect(screen.queryByText("A schedule please")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
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

  describe("quick replies (AI-07)", () => {
    const question: Event[] = [
      { type: "text", text: "Which track are you on?" },
      { type: "done", data: { quick_replies: ["Fall & Winter", "Winter & Spring", "Online student"] } },
    ];

    it("shows the fixed answers and sends the clicked one as the student's message", async () => {
      let n = 0;
      const calls = fakeBackend({
        "POST /api/chat": () =>
          sse(n++ === 0 ? question : [{ type: "text", text: "How many credits do you want?" }, { type: "done" }]),
      });
      const user = await ask("Help me plan my semester");

      const replies = within(await screen.findByRole("list", { name: "Quick replies" }));
      expect(replies.getAllByRole("button").map((b) => b.textContent)).toEqual([
        "Fall & Winter",
        "Winter & Spring",
        "Online student",
      ]);
      await user.click(replies.getByRole("button", { name: "Winter & Spring" }));

      await screen.findByText("How many credits do you want?");
      expect(calls.filter((c) => c.path === "/api/chat").map((c) => c.body)).toEqual([
        { message: "Help me plan my semester" },
        { message: "Winter & Spring" },
      ]);
      // It is in the conversation like a typed message, and the old buttons are gone.
      expect(screen.getByText("Winter & Spring")).toBeInTheDocument();
      expect(screen.queryByRole("list", { name: "Quick replies" })).not.toBeInTheDocument();
    });

    it("can be used with the keyboard only", async () => {
      let n = 0;
      const calls = fakeBackend({
        "POST /api/chat": () => sse(n++ === 0 ? question : [{ type: "text", text: "Got it." }, { type: "done" }]),
      });
      const user = await ask("Help me plan my semester");
      const first = await screen.findByRole("button", { name: "Fall & Winter" });
      first.focus();
      await user.tab();
      expect(screen.getByRole("button", { name: "Winter & Spring" })).toHaveFocus();
      await user.keyboard("{Enter}");
      await screen.findByText("Got it.");
      expect(calls.filter((c) => c.path === "/api/chat")[1]?.body).toEqual({ message: "Winter & Spring" });
    });

    it("shows none when the reply has no fixed answers, and keeps a typed draft", async () => {
      fakeBackend({ "POST /api/chat": () => sse(question) });
      const user = await ask("Help me plan my semester");
      await screen.findByRole("list", { name: "Quick replies" });
      await user.type(screen.getByLabelText(/what you want in your schedule/i), "I am not sure");
      expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("I am not sure");
    });

    it("ignores a malformed list", async () => {
      fakeBackend({
        "POST /api/chat": () =>
          sse([{ type: "text", text: "Which days?" }, { type: "done", data: { quick_replies: "Fridays" } }]),
      });
      await ask("Help me plan my semester");
      await screen.findByText("Which days?");
      expect(screen.queryByRole("list", { name: "Quick replies" })).not.toBeInTheDocument();
    });
  });
});
