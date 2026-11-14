import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import audit from "../../../fixtures/audit.json";
import type { DegreeAudit } from "../api/schemas";
import { fakeBackend, json, renderApp } from "../test/utils";

const sampleAudit = audit as DegreeAudit;
const unmet = sampleAudit.requirements!.filter((r) => r.status === "not_met");

function backend() {
  return fakeBackend({
    "POST /api/session": () =>
      json({ student: { id: "stub-session", consented_at: "2026-11-13T10:00:00Z" } }),
    "POST /api/audit/sample": () => json(sampleAudit),
    "GET /api/requirements/remaining": () => json(unmet),
    "DELETE /api/me": () => new Response(null, { status: 204 }),
  });
}

describe("Consent screen", () => {
  it("says what is stored, that the audit goes to the Claude API, that the PDF is deleted, and how to delete all data", () => {
    backend();
    renderApp("/");

    expect(screen.getByRole("heading", { level: 1, name: "Before you start" })).toBeInTheDocument();
    expect(screen.getByText(/we store your degree audit/i)).toBeInTheDocument();
    expect(screen.getByText(/sent to the claude api/i)).toBeInTheDocument();
    expect(screen.getByText(/pdf is deleted/i)).toBeInTheDocument();
    expect(screen.getByText(/delete all your data/i)).toBeInTheDocument();
  });

  it("states that the app never asks for a BYU-Idaho username or password, and has no such field", () => {
    backend();
    const { container } = renderApp("/");

    expect(
      screen.getByText(/never asks for your byu-idaho username or password/i),
    ).toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByLabelText(/username|password/i)).toBeNull();
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  });

  it("keeps every continue button disabled until the box is checked", async () => {
    backend();
    const user = userEvent.setup();
    renderApp("/");

    const box = screen.getByRole("checkbox", {
      name: "I understand what is stored and how to delete it",
    });
    const sample = screen.getByRole("button", { name: "Use sample audit" });
    expect(box).not.toBeChecked();
    expect(sample).toBeDisabled();

    await user.click(box);
    expect(sample).toBeEnabled();

    await user.click(box);
    expect(sample).toBeDisabled();
  });

  it("'Use sample audit' records consent, loads the fixture audit and opens 'What you still need'", async () => {
    const calls = backend();
    const user = userEvent.setup();
    renderApp("/");

    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Use sample audit" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "What you still need" }),
    ).toBeInTheDocument();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /api/session",
      "POST /api/audit/sample",
      "GET /api/requirements/remaining",
    ]);
    expect(calls[0].body).toEqual({ consent: true });
  });

  it("shows a clear message when the session cannot start, and stays on the consent screen", async () => {
    fakeBackend({ "POST /api/session": () => json({ detail: "down" }, 503) });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Use sample audit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't start/i);
    expect(screen.getByRole("heading", { level: 1, name: "Before you start" })).toBeInTheDocument();
  });

  it("reaches every control with Tab, in order, and every field has a label", async () => {
    backend();
    const user = userEvent.setup();
    renderApp("/");

    const box = screen.getByLabelText("I understand what is stored and how to delete it");
    await user.click(box);
    (document.activeElement as HTMLElement).blur();

    const expected = [
      screen.getByRole("link", { name: /course planner/i }),
      box,
      screen.getByRole("button", { name: "Use sample audit" }),
      screen.getByRole("button", { name: "Delete my data" }),
    ];
    const order: Element[] = [];
    for (let i = 0; i < expected.length; i += 1) {
      await user.tab();
      order.push(document.activeElement!);
    }
    expect(order).toEqual(expected);
  });

  it("'Delete my data' deletes everything and returns to the consent screen", async () => {
    const calls = backend();
    const user = userEvent.setup();
    renderApp("/requirements");

    await screen.findByRole("heading", { level: 1, name: "What you still need" });
    await user.click(screen.getByRole("button", { name: "Delete my data" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Before you start" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/your data was deleted/i);
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/me")).toBe(true),
    );
  });
});
