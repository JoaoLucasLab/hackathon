import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import golden from "../../../fixtures/audits/software-engineering-minor/expected.json";
import transfer from "../../../fixtures/audits/transfer-student/expected.json";
import sample from "../../../fixtures/audit.json";
import type { DegreeAudit } from "../api/schemas";
import { fakeBackend, json, renderApp, type Handler } from "../test/utils";

const pdf = () => new File(["%PDF-1.7 test"], "audit.pdf", { type: "application/pdf" });

function backend(upload: Handler, extra: Record<string, Handler> = {}) {
  return fakeBackend({
    "POST /api/session": () => json({ student: { id: "s" } }),
    "POST /api/audit": upload,
    "PUT /api/audit": async (req) => json(await req.json()),
    "GET /api/requirements/remaining": () => json([]),
    ...extra,
  });
}

async function uploadAudit(audit: DegreeAudit | Handler) {
  const calls = backend(typeof audit === "function" ? audit : () => json(audit));
  const user = userEvent.setup();
  renderApp("/audit");
  await user.upload(screen.getByLabelText(/choose your degree audit pdf/i), pdf());
  await user.click(screen.getByRole("button", { name: "Read my audit" }));
  return { calls, user };
}

function withFlags(audit: DegreeAudit, flags: DegreeAudit["validation_flags"]): DegreeAudit {
  return { ...structuredClone(audit), validation_flags: flags };
}

const today = new Date().toISOString().slice(0, 10);
const fresh = (a: DegreeAudit): DegreeAudit => ({ ...structuredClone(a), audit_date: today });

describe("Audit upload", () => {
  it("shows a loading state while the audit is read", async () => {
    await uploadAudit(() => new Promise<Response>(() => {}));
    expect(await screen.findByRole("status")).toHaveTextContent(/reading your audit/i);
    expect(screen.getByRole("status")).toHaveTextContent(/up to a minute/i);
  });

  it("sends the PDF once, after recording consent", async () => {
    const { calls } = await uploadAudit(fresh(sample as DegreeAudit));
    await screen.findByRole("heading", { name: "Check your audit" });
    const posted = calls.filter((c) => c.path === "/api/audit");
    expect(calls.map((c) => `${c.method} ${c.path}`).slice(0, 2)).toEqual([
      "POST /api/session",
      "POST /api/audit",
    ]);
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toBe("multipart/form-data");
  });

  it("refuses a file that is not a PDF before sending it", async () => {
    const calls = backend(() => json(sample));
    const user = userEvent.setup({ applyAccept: false });
    renderApp("/audit");
    await user.upload(
      screen.getByLabelText(/choose your degree audit pdf/i),
      new File(["hi"], "notes.txt", { type: "text/plain" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/not a pdf/i);
    expect(screen.getByRole("button", { name: "Read my audit" })).toBeDisabled();
    expect(calls).toHaveLength(0);
  });

  it("offers Try again and Use sample audit when the audit can't be read", async () => {
    let fail = true;
    const { user } = await uploadAudit(() =>
      fail ? json({ detail: "We couldn't read this audit." }, 422) : json(fresh(sample as DegreeAudit)),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't read this audit.");
    expect(screen.getByRole("button", { name: "Use sample audit" })).toBeInTheDocument();

    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Check your audit" })).toBeInTheDocument();
  });

  it("'Use sample audit' after a failure loads the sample", async () => {
    const calls = backend(() => json({ detail: "x" }, 422), {
      "POST /api/audit/sample": () => json(sample),
    });
    const user = userEvent.setup();
    renderApp("/audit");
    await user.upload(screen.getByLabelText(/choose your degree audit pdf/i), pdf());
    await user.click(screen.getByRole("button", { name: "Read my audit" }));
    await user.click(await screen.findByRole("button", { name: "Use sample audit" }));
    expect(await screen.findByRole("heading", { name: "What you still need" })).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/audit/sample")).toBe(true);
  });
});

describe("Check your audit", () => {
  it("shows an empty state when there is no audit to check", () => {
    backend(() => json(sample));
    renderApp("/audit/confirm");
    expect(screen.getByText(/no audit to check yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload my audit" })).toBeInTheDocument();
  });

  it("shows major, catalog year, audit date, groups, statuses, credits and options", async () => {
    const audit = fresh(sample as DegreeAudit);
    await uploadAudit(audit);
    await screen.findByRole("heading", { name: "Check your audit" });

    expect(screen.getByText(new RegExp(audit.major.replace(/[()]/g, "\\$&")))).toBeInTheDocument();
    expect(screen.getByText(/2024-2025 catalog/)).toBeInTheDocument();
    expect(screen.getByText(/audit from /)).toBeInTheDocument();

    const groups = new Set(audit.requirements!.map((r) => r.group));
    for (const group of groups) expect(screen.getByText(group)).toBeInTheDocument();
    expect(screen.getAllByText(/· Not met/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/· In progress/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/· Complete/).length).toBeGreaterThan(0);

    const unmet = audit.requirements!.find((r) => r.status === "not_met")!;
    const row = screen.getByText(unmet.name).closest("li")!;
    expect(within(row).getByText(`${unmet.credits_needed} credits still needed`)).toBeInTheDocument();
    for (const code of unmet.options ?? []) expect(within(row).getByText(code)).toBeInTheDocument();
  });

  it("labels in-progress courses 'pending grade' and keeps transfer equivalents", async () => {
    await uploadAudit(fresh(transfer as DegreeAudit));
    await screen.findByRole("heading", { name: "Check your audit" });
    expect(screen.getAllByText(/pending grade/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Transfer, counts as CSE 110/).length).toBeGreaterThan(0);
  });

  it("asks for the track when the audit does not show it, and blocks saving until then", async () => {
    const { calls, user } = await uploadAudit(fresh(golden as DegreeAudit));
    const group = await screen.findByRole("group", { name: "Which track are you on?" });
    for (const label of ["Fall & Winter", "Winter & Spring", "Spring & Fall", "Online (no track)"])
      expect(within(group).getByLabelText(label)).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save my audit" });
    expect(save).toBeDisabled();

    await user.click(within(group).getByLabelText("Winter & Spring"));
    await user.click(save);
    await screen.findByRole("heading", { name: "What you still need" });
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/audit");
    expect((put?.body as DegreeAudit).track).toBe("winter_spring");
  });

  it("highlights flagged values and saves the student's corrections", async () => {
    const audit = withFlags(fresh(sample as DegreeAudit), [
      {
        field: "requirements[4].options[0]",
        kind: "unknown_course",
        message:
          "CSE 999 isn't in this semester's course list. It may not be offered this term, or the code may be wrong.",
      },
      {
        field: "total_credits_earned",
        kind: "credit_mismatch",
        message: "The audit says 1 credits earned, but the courses add up to 15.",
      },
      {
        field: "requirements[3].status",
        kind: "invalid_status",
        message: "Programming with Data Structures is marked not met but needs no more credits.",
      },
    ]);
    audit.requirements![4].options = ["CSE 999"];
    audit.total_credits_earned = 1;
    const { calls, user } = await uploadAudit(audit);

    const list = await screen.findByRole("heading", { name: "3 values to check" });
    expect(list).toBeInTheDocument();
    expect(screen.getByText(/CSE 999 isn't in this semester's course list/)).toBeInTheDocument();

    const code = screen.getByLabelText(/course option for/i);
    await user.clear(code);
    await user.type(code, "cse 110");
    const earned = screen.getByLabelText("Total credits earned");
    await user.clear(earned);
    await user.type(earned, "15");
    await user.selectOptions(screen.getByLabelText(/status of programming with data/i), "complete");
    expect(screen.getAllByText(/^Edited\./)).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Save my audit" }));
    await screen.findByRole("heading", { name: "What you still need" });
    const saved = calls.find((c) => c.method === "PUT")?.body as DegreeAudit;
    expect(saved.requirements![4].options).toEqual(["CSE 110"]);
    expect(saved.total_credits_earned).toBe(15);
    expect(saved.requirements![3].status).toBe("complete");
    expect(saved.validation_flags).toEqual([]);
  });

  it("shows the date of an old audit and asks for a fresh one", async () => {
    const audit = withFlags(sample as DegreeAudit, [
      { field: "audit_date", kind: "stale_audit", message: "old" },
    ]);
    const { user } = await uploadAudit(audit);
    expect(await screen.findByText(/this audit is from november 10, 2026/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload a fresh audit" }));
    expect(await screen.findByRole("heading", { name: "Upload your degree audit" })).toBeInTheDocument();
  });

  it("says so when saving fails, without leaving the screen", async () => {
    const calls = backend(() => json(fresh(sample as DegreeAudit)), {
      "PUT /api/audit": () => json({ detail: "x" }, 500),
    });
    const user = userEvent.setup();
    renderApp("/audit");
    await user.upload(screen.getByLabelText(/choose your degree audit pdf/i), pdf());
    await user.click(screen.getByRole("button", { name: "Read my audit" }));
    await user.click(await screen.findByRole("button", { name: "Save my audit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't save your audit/i);
    expect(screen.getByRole("heading", { name: "Check your audit" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(true);
  });
});
