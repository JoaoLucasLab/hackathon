import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import professorsFixture from "../../../fixtures/professors.json";
import auditFixture from "../../../fixtures/audit.json";
import type { ChatEvent, Professor, Schedule, ScheduleExplanation } from "../api/schemas";
import buildResult from "../test/data/build_schedules.json";
import calendarSchedule from "../test/data/calendar_schedule.json";
import { fakeBackend, json, renderApp, type Handler } from "../test/utils";
import { ScheduleDetail } from "./ScheduleDetail";

const schedule = calendarSchedule as unknown as Schedule;
const ADVISING = "Confirm with BYU-Idaho Academic Advising.";

const goodExplanation: ScheduleExplanation = {
  schedule_id: schedule.id,
  available: true,
  why: "CSE 212 and CSE 310 move your major forward, and nothing starts before your start time.",
  tradeoffs: ["CSE 310 is a Second Block class, so it runs at a faster pace."],
  advising_note: ADVISING,
};

/** A fake backend whose favorites live on the "server", like the real session store. */
function backend(explanation: ScheduleExplanation | "error" = goodExplanation) {
  const favorites = new Set<string>();
  const professors = (): Professor[] =>
    (professorsFixture as Professor[]).map((p) => ({ ...p, is_favorite: favorites.has(p.id) }));
  const routes: Record<string, Handler> = {
    "GET /api/professors": () => json(professors()),
    "GET /api/requirements/remaining": () => json(auditFixture.requirements),
    "POST /api/schedules/explain": () =>
      explanation === "error" ? json({ detail: "boom" }, 500) : json(explanation),
  };
  for (const p of professorsFixture) {
    routes[`PUT /api/professors/${p.id}/favorite`] = async (req) => {
      const body = (await req.json()) as { favorite: boolean };
      if (body.favorite) favorites.add(p.id);
      else favorites.delete(p.id);
      return json({ professor_id: p.id, favorite: body.favorite, updated_at: "2026-11-14T00:00:00Z" });
    };
  }
  const calls = fakeBackend(routes);
  return { calls, favorites };
}

function renderDetail(onBack = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ScheduleDetail schedule={schedule} onBack={onBack} />
    </QueryClientProvider>,
  );
  return { ...view, onBack };
}

function row(code: string): HTMLElement {
  const classes = screen.getByRole("list", { name: "Classes" });
  const heading = within(classes).getByRole("heading", { name: new RegExp(`^${code}`) });
  return heading.closest("li") as HTMLElement;
}

describe("ScheduleDetail", () => {
  it("shows the requirement each class fills, its professor with a star, an RMP link and seats as of a time", async () => {
    backend();
    renderDetail();
    const cse212 = row("CSE 212-02");
    expect(within(cse212).getByText("Programming with Data Structures")).toBeInTheDocument();
    expect(await within(cse212).findByRole("button", { name: "Star Marcus Hale" })).toBeInTheDocument();
    const link = within(cse212).getByRole("link", { name: /See on Rate My Professors/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link.getAttribute("href")).toMatch(/^https:\/\/www\.ratemyprofessors\.com\//);

    for (const item of within(screen.getByRole("list", { name: "Classes" })).getAllByRole("listitem")) {
      if (item.parentElement?.getAttribute("aria-label") !== "Classes") continue;
      expect(item.textContent).toMatch(/Seats as of [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M/);
    }
  });

  it("never shows a rating", async () => {
    backend();
    renderDetail();
    await screen.findAllByRole("button", { name: /^Star / });
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/rating|quality|difficulty|\d(\.\d)? ?\/ ?5\b|would take again/i);
  });

  it('shows prerequisite warnings as "Check this before registering", not as errors', async () => {
    backend();
    renderDetail();
    const warning = within(row("CSE 212-02")).getByText(/^Check this before registering: needs CSE 111/);
    const line = warning.closest("p") as HTMLElement;
    expect(line).toHaveClass("text-warn");
    expect(line).not.toHaveAttribute("role", "alert");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows Claude's why and trade-offs, asked for with this schedule only", async () => {
    const { calls } = backend();
    renderDetail();
    expect(await screen.findByText(goodExplanation.why as string)).toBeInTheDocument();
    expect(screen.getByText(goodExplanation.tradeoffs?.[0] as string)).toBeInTheDocument();
    const request = calls.find((c) => c.path === "/api/schedules/explain");
    expect(request?.body).toEqual({ schedule });
  });

  it("falls back to the structured rules when there is no grounded text", async () => {
    backend({ schedule_id: schedule.id, available: false, tradeoffs: [], advising_note: ADVISING });
    renderDetail();
    expect(await screen.findByText(/No written summary for this one/)).toBeInTheDocument();
    expect(screen.getByText("Keeps: Start time, Credit range")).toBeInTheDocument();
    expect(screen.getByText("Misses: Friday off")).toBeInTheDocument();
  });

  it("shows the structured rules when the summary request fails", async () => {
    backend("error");
    renderDetail();
    expect(await screen.findByText(/We couldn't load the summary/)).toBeInTheDocument();
    expect(screen.getByText("Keeps: Start time, Credit range")).toBeInTheDocument();
  });

  it("expands a class to show up to 2 backup sections", async () => {
    backend();
    const user = userEvent.setup();
    renderDetail();
    const cse212 = row("CSE 212-02");
    const toggle = within(cse212).getByRole("button", { name: /Show 2 backup sections/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(cse212).queryByText("CSE 212-01")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(cse212).getByText("CSE 212-01")).toBeInTheDocument();
    expect(within(cse212).getByText("CSE 212-04")).toBeInTheDocument();
    expect(within(row("WDD 231-02")).queryByRole("button", { name: /backup/ })).not.toBeInTheDocument();
  });

  it("ends with the advising note and promises no seat", async () => {
    backend();
    renderDetail();
    await screen.findByText(goodExplanation.why as string);
    const article = screen.getByRole("article");
    expect(article.lastElementChild?.textContent).toBe(ADVISING);
    expect(article.textContent).not.toMatch(/guarantee|seat is yours|reserved for you|you will get a seat/i);
  });

  it("shows the week calendar", () => {
    backend();
    renderDetail();
    expect(screen.getByRole("region", { name: "Tuesday" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Saturday" })).toBeInTheDocument();
  });

  it("keeps a starred professor starred after a reload", async () => {
    const { calls, favorites } = backend();
    const user = userEvent.setup();
    const first = renderDetail();
    await user.click(await within(row("CSE 212-02")).findByRole("button", { name: "Star Marcus Hale" }));
    await waitFor(() => expect(favorites.has("p-hale")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ favorite: true });
    first.unmount();

    // A reload: a fresh query cache, reading the stars back from the server.
    renderDetail();
    const star = await within(row("CSE 212-02")).findByRole("button", { name: "Unstar Marcus Hale" });
    expect(star).toHaveAttribute("aria-pressed", "true");
  });

  it('shows no "Professor not listed yet" while professors are still loading', async () => {
    backend();
    fakeBackend({
      "GET /api/professors": () => new Promise<Response>(() => {}), // never answers
      "GET /api/requirements/remaining": () => json(auditFixture.requirements),
      "POST /api/schedules/explain": () => json(goodExplanation),
    });
    renderDetail();
    await screen.findByText(goodExplanation.why as string);
    expect(screen.queryByText("Professor not listed yet")).not.toBeInTheDocument();
  });

  it("goes back to all schedules", async () => {
    backend();
    const user = userEvent.setup();
    const { onBack } = renderDetail();
    await user.click(screen.getByRole("button", { name: "All schedules" }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});

type Event = Partial<ChatEvent> & { type: ChatEvent["type"] };

function sse(events: Event[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

async function chatOnce(result: Record<string, unknown>, extra: Record<string, Handler> = {}) {
  const calls = fakeBackend({
    "POST /api/chat": () =>
      sse([
        { type: "tool_result", tool: "build_schedules", data: result },
        { type: "text", text: "Done." },
        { type: "done" },
      ]),
    "GET /api/professors": () => json(professorsFixture),
    "GET /api/requirements/remaining": () => json(auditFixture.requirements),
    "POST /api/schedules/explain": () => json(goodExplanation),
    ...extra,
  });
  const user = userEvent.setup();
  const { queryClient } = renderApp("/planner");
  queryClient.setQueryData(["audit"], auditFixture);
  await user.type(screen.getByLabelText(/what you want in your schedule/i), "No Fridays");
  await user.click(screen.getByRole("button", { name: "Send" }));
  return { calls, user };
}

describe("Planner with schedule details", () => {
  it("opens one schedule and comes back to all of them", async () => {
    const { user } = await chatOnce(buildResult as Record<string, unknown>);
    await user.click(await screen.findByRole("button", { name: "See details for option 2" }));
    expect(screen.getByRole("heading", { name: "Option 2" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Schedule options" })).not.toBeInTheDocument();
    // The chat is hidden, not unmounted. A display class on the same element would
    // override the `hidden` attribute in the real CSS (jsdom applies no Tailwind).
    const chatWrapper = screen.getByLabelText(/what you want in your schedule/i).closest("[hidden]");
    expect(chatWrapper).not.toBeNull();
    expect(chatWrapper?.className ?? "").not.toMatch(/\b(flex|grid|block|inline[\w-]*)\b/);
    await user.click(screen.getByRole("button", { name: "All schedules" }));
    expect(screen.getByRole("list", { name: "Schedule options" })).toBeInTheDocument();
  });

  it("shows a relaxation hint with a one-click Apply this change", async () => {
    const patch = { ...buildResult.constraints, days_off: [] };
    const relaxed = {
      ...buildResult,
      schedules: [],
      relaxation: {
        constraint: "days_off",
        change: "allow a class on Friday",
        schedules_available: 3,
        patch,
      },
    };
    const { calls, user } = await chatOnce(relaxed, {
      "PUT /api/constraints": async (req) => json(await req.json()),
      "POST /api/schedules/build": () => json(buildResult),
    });
    expect(
      await screen.findByText("No schedule fits all of your rules. If you allow a class on Friday, 3 schedules would fit."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply this change" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/schedules/build")).toBe(true));
    expect(calls.find((c) => c.path === "/api/constraints")?.body).toEqual(patch);
    expect(await screen.findAllByRole("article")).toHaveLength(3);
  });
});
