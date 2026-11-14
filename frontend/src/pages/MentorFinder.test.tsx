import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import professors from "../../../fixtures/professors.json";
import { fakeBackend, json, renderApp } from "../test/utils";

const professor = professors[0]!;

describe("Professor screen", () => {
  it("shows a loading state, then real professor facts and source links", async () => {
    let respond!: (response: Response) => void;
    fakeBackend({ "GET /api/professors": () => new Promise((resolve) => { respond = resolve; }) });
    renderApp("/professors");
    expect(screen.getByRole("status")).toHaveTextContent("Finding professors");
    await vi.waitFor(() => expect(respond).toBeDefined());
    respond(json([professor]));
    expect(await screen.findByRole("heading", { name: `${professor.first_name} ${professor.last_name}` })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See on Rate My Professors/ })).toHaveAttribute("href", professor.rmp_url);
  });
  it("retries a failed request", async () => {
    let fail = true;
    fakeBackend({ "GET /api/professors": () => fail ? json({}, 500) : json([professor]) });
    renderApp("/professors");
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't load professors");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("heading", { name: `${professor.first_name} ${professor.last_name}` })).toBeInTheDocument();
  });
  it("searches with existing topic tags and keeps favorites current in search results", async () => {
    let favorite = false;
    const tag = professor.topic_tags![0]!;
    const calls = fakeBackend({
      "GET /api/professors": () => json([{ ...professor, is_favorite: favorite }]),
      "POST /api/mentors/search": () => json([{ professor: { ...professor, is_favorite: false }, reasons: [], score: 1 }]),
      [`PUT /api/professors/${professor.id}/favorite`]: () => { favorite = true; return json({ professor_id: professor.id, favorite: true }); },
    });
    renderApp("/professors");
    await screen.findByRole("heading", { name: `${professor.first_name} ${professor.last_name}` });
    await userEvent.type(screen.getByLabelText(/Search professors/), tag);
    await userEvent.click(screen.getByRole("button", { name: "Find professors" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/mentors/search")).toBe(true));
    expect(calls.find((c) => c.path === "/api/mentors/search")?.body).toEqual({ goal: "research", tags: [tag] });
    await userEvent.click(await screen.findByRole("button", { name: `Star ${professor.first_name} ${professor.last_name}` }));
    expect(await screen.findByRole("button", { name: `Unstar ${professor.first_name} ${professor.last_name}` })).toHaveAttribute("aria-pressed", "true");
  });
  it("creates an editable email draft and copies the student's edits", async () => {
    const showModal = vi.fn(function (this: HTMLDialogElement) { this.setAttribute("open", ""); });
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: showModal });
    const calls = fakeBackend({
      "GET /api/professors": () => json([professor]),
      [`POST /api/mentors/${professor.id}/email-draft`]: () => json({ professor_id: professor.id, subject: "Research question", body: "Could we meet?" }),
    });
    const user = userEvent.setup();
    const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderApp("/professors");
    await user.click(await screen.findByRole("button", { name: "Draft email" }));
    expect(showModal).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("checkbox", { name: "Mention my grade when available" }));
    await user.click(screen.getByRole("button", { name: "Create draft" }));
    const message = await screen.findByLabelText("Message");
    await user.clear(message);
    await user.type(message, "Could we meet next week?");
    await user.click(screen.getByRole("button", { name: "Copy draft" }));
    expect(copy).toHaveBeenCalledWith("Research question\n\nCould we meet next week?");
    expect(calls.find((c) => c.path.endsWith("/email-draft"))?.body).toEqual({ goal: "research", mention_grade: true });
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close email draft" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    copy.mockRestore();
    delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
  });

  it("asks for another topic instead of inventing a tag", async () => {
    const calls = fakeBackend({ "GET /api/professors": () => json([professor]) });
    renderApp("/professors");
    await screen.findByRole("heading", { name: `${professor.first_name} ${professor.last_name}` });
    await userEvent.type(screen.getByLabelText(/Search professors/), "unknown-topic");
    await userEvent.click(screen.getByRole("button", { name: "Find professors" }));
    expect(screen.getByText(/No professors match this topic yet/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});
