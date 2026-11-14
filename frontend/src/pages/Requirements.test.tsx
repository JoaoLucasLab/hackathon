import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import audit from "../../../fixtures/audit.json";
import type { AuditRequirement, DegreeAudit } from "../api/schemas";
import { fakeBackend, json, renderApp } from "../test/utils";

const unmet: AuditRequirement[] = (audit as DegreeAudit).requirements!.filter(
  (r) => r.status === "not_met",
);

function remaining(handler: () => Response | Promise<Response>) {
  return fakeBackend({ "GET /api/requirements/remaining": handler });
}

describe("What you still need", () => {
  it("shows a loading state while requirements load", () => {
    remaining(() => new Promise<Response>(() => {}));
    renderApp("/requirements");

    expect(screen.getByRole("status", { name: "Loading requirements" })).toBeInTheDocument();
  });

  it("shows an empty state when nothing is left", async () => {
    remaining(() => json([]));
    renderApp("/requirements");

    expect(await screen.findByText(/your audit shows nothing left to plan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start over" })).toBeInTheDocument();
  });

  it("shows an error state with a retry that loads the list", async () => {
    let fail = true;
    remaining(() => (fail ? json({ detail: "boom" }, 500) : json(unmet)));
    const user = userEvent.setup();
    renderApp("/requirements");

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't load your requirements/i);

    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(unmet[0].name)).toBeInTheDocument();
  });

  it("lists each unmet requirement with its credits and course options", async () => {
    remaining(() => json(unmet));
    const user = userEvent.setup();
    renderApp("/requirements");

    await screen.findByText(unmet[0].name);
    const showAll = screen.queryByRole("button", { name: `Show all ${unmet.length}` });
    if (showAll) await user.click(showAll);

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(unmet.length);
    unmet.forEach((req, i) => {
      const row = within(rows[i]);
      expect(row.getByText(req.name)).toBeInTheDocument();
      const credits = `${req.credits_needed} ${req.credits_needed === 1 ? "credit" : "credits"} needed`;
      expect(row.getByText(credits)).toBeInTheDocument();
      for (const code of req.options ?? []) expect(row.getByText(code)).toBeInTheDocument();
    });
  });

  it("shows at most 6 requirements before 'Show all'", async () => {
    remaining(() => json(unmet));
    renderApp("/requirements");

    await screen.findByText(unmet[0].name);
    expect(screen.getAllByRole("listitem")).toHaveLength(Math.min(6, unmet.length));
  });

  it("reaches every control with Tab", async () => {
    remaining(() => json(unmet));
    const user = userEvent.setup();
    renderApp("/requirements");
    await screen.findByText(unmet[0].name);

    const reached = new Set<Element>();
    for (let i = 0; i < 10; i += 1) {
      await user.tab();
      if (document.activeElement) reached.add(document.activeElement);
    }
    for (const button of screen.getAllByRole("button")) expect(reached).toContain(button);
  });
});
