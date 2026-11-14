import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeBackend, json, renderApp } from "../test/utils";

describe("Main screens", () => {
  it("opens Plan first and navigates to the empty Schedules screen", async () => {
    fakeBackend({});
    renderApp("/");
    expect(screen.getByRole("heading", { name: "Plan a semester that fits your week" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(screen.getByRole("link", { name: "Schedules" }));
    expect(screen.getByText(/No schedules yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Schedules" })).toHaveAttribute("aria-current", "page");
  });
  it("keeps consent before loading a sample audit", async () => {
    const calls = fakeBackend({});
    renderApp("/");
    await userEvent.click(screen.getByRole("link", { name: "Try the sample audit" }));
    expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use sample audit" })).toBeDisabled();
    expect(calls).toHaveLength(0);
  });
  it("preserves the prompt through consent and audit review without sending it early", async () => {
    const audit = (await import("../../../fixtures/audit.json")).default;
    const calls = fakeBackend({
      "POST /api/session": () => json({}),
      "POST /api/audit/sample": () => json(audit),
      "GET /api/requirements/remaining": () => json(audit.requirements.filter((r) => r.status === "not_met")),
    });
    renderApp("/");
    await userEvent.type(screen.getByLabelText(/what you want in your schedule/i), "Fridays off");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Use sample audit" }));
    await userEvent.click(await screen.findByRole("button", { name: "Plan my schedule" }));
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("Fridays off");
  });
  it("resumes after a full refresh using the existing API without repeating setup", async () => {
    const audit = (await import("../../../fixtures/audit.json")).default;
    const calls = fakeBackend({
      "POST /api/session": () => json({}),
      "POST /api/audit/sample": () => json(audit),
      "GET /api/requirements/remaining": () => json([]),
      "POST /api/chat": () => new Response('data: {"type":"text","text":"Welcome back."}\n\ndata: {"type":"done"}\n\n'),
    });
    const first = renderApp("/consent");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Use sample audit" }));
    await screen.findByRole("heading", { name: "What you still need" });
    first.unmount();
    const callsBeforeRefresh = calls.length;
    const refreshed = renderApp("/");
    expect(refreshed.queryClient.getQueryData(["audit"])).toBeUndefined();
    await userEvent.type(screen.getByLabelText(/what you want in your schedule/i), "Fridays off");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Welcome back.")).toBeInTheDocument();
    expect(calls.slice(callsBeforeRefresh).map((c) => `${c.method} ${c.path}`)).toEqual([
      "GET /api/requirements/remaining", "POST /api/chat",
    ]);
    expect(Object.values(localStorage)).toEqual(["true"]);
  });

  it.each([401, 403, 404])("returns expired sessions (%s) to consent with their draft intact", async (status) => {
    localStorage.setItem("planning-setup-complete", "true");
    const calls = fakeBackend({ "GET /api/requirements/remaining": () => json({}, status) });
    renderApp("/");
    await userEvent.type(screen.getByLabelText(/what you want in your schedule/i), "Keep Fridays free");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("heading", { name: "Before you start" });
    expect(localStorage.getItem("planning-setup-complete")).toBeNull();
    await userEvent.click(screen.getByRole("link", { name: "Plan" }));
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("Keep Fridays free");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("keeps the prompt and permits retry when restoring the session temporarily fails", async () => {
    localStorage.setItem("planning-setup-complete", "true");
    let failing = true;
    const calls = fakeBackend({
      "GET /api/requirements/remaining": () => failing ? json({}, 503) : json([]),
      "POST /api/chat": () => new Response('data: {"type":"text","text":"Ready again."}\n\ndata: {"type":"done"}\n\n'),
    });
    renderApp("/");
    await userEvent.type(screen.getByLabelText(/what you want in your schedule/i), "Fridays off");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't restore your planning session");
    expect(screen.getByLabelText(/what you want in your schedule/i)).toHaveValue("Fridays off");
    expect(localStorage.getItem("planning-setup-complete")).toBe("true");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Ready again.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("opens Professors directly and shows the empty state", async () => {
    fakeBackend({ "GET /api/professors": () => json([]) });
    renderApp("/professors");
    expect(await screen.findByText(/No professors match this topic yet/)).toBeInTheDocument();
  });
});
