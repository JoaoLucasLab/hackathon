import { ArrowUp, LoaderCircle, Plus } from "lucide-react";
import { useId, useRef, type FormEvent, type KeyboardEvent } from "react";

import { Link } from "react-router-dom";
import { streamChat } from "../api/chat";
import type { ChatEvent } from "../api/schemas";
import { usePlanningState, type ChatTurn } from "../pages/PlanningState";
import { Icon, ICON_STROKE } from "./ui/Icon";

/** What the student sees while a tool runs. Never the raw tool name or arguments. */
const TOOL_STATUS: Record<string, string> = {
  get_remaining_requirements: "Reading your requirements",
  search_sections: "Looking up sections",
  check_prerequisites: "Checking prerequisites",
  build_schedules: "Building schedules",
  get_professor_profile: "Looking up the professor",
  toggle_favorite_professor: "Updating your favorites",
  find_mentors: "Finding mentors",
  draft_outreach_email: "Drafting the email",
};

const STARTERS = [
  { label: "No mornings", text: "No morning classes" },
  { label: "Fridays off", text: "No classes on Fridays" },
  { label: "12 to 15 credits", text: "12 to 15 credits" },
  { label: "Favorite professors", text: "Only my favorite professors" },
];
const STARTER_COLORS = ["bg-sq-sage", "bg-sq-clay", "bg-sq-sky", "bg-sq-butter"];

/** The `done` event may carry fixed answers for the question the assistant just asked. */
function quickRepliesFrom(event: ChatEvent): string[] | undefined {
  const raw = (event.data as { quick_replies?: unknown } | null | undefined)?.quick_replies;
  if (!Array.isArray(raw)) return undefined;
  const options = raw.filter((o): o is string => typeof o === "string" && o.trim() !== "");
  return options.length > 0 ? options : undefined;
}

interface ChatPanelProps {
  /** Every event, so the page can show chips and schedule cards. */
  onEvent?: (event: ChatEvent) => void;
  beforeSend?: (signal: AbortSignal) => boolean | Promise<boolean>;
}

export function ChatPanel({ onEvent, beforeSend }: ChatPanelProps) {
  const inputId = useId();
  const {
    draft, setDraft, turns, setTurns, busy, setBusy,
    sendError, setSendError, nextTurnId, activeRequest,
  } = usePlanningState();
  const lastEvent = useRef<ChatEvent["type"] | null>(null);

  async function send(message: string) {
    const text = message.trim();
    if (!text || activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setBusy(true);
    setSendError(null);
    let assistantId: number | null = null;
    const updateReply = (patch: (turn: ChatTurn) => ChatTurn) =>
      setTurns((all) => all.map((turn) => turn.id === assistantId ? patch(turn) : turn));

    try {
      if (beforeSend && !(await beforeSend(controller.signal))) return;
      if (controller.signal.aborted) return;
      setDraft((current) => current === message ? "" : current);
      const studentId = nextTurnId.current++;
      const replyId = nextTurnId.current++;
      assistantId = replyId;
      setTurns((all) => [
        ...all,
        { id: studentId, role: "student", text },
        { id: replyId, role: "assistant", text: "" },
      ]);
      lastEvent.current = null;
      await streamChat(text, (event) => {
        if (controller.signal.aborted) return;
        onEvent?.(event);
        const afterTool = lastEvent.current === "tool_result" || lastEvent.current === "tool_call";
        lastEvent.current = event.type;
        if (event.type === "text") {
          updateReply((turn) => ({
            ...turn,
            text: turn.text + (afterTool && turn.text ? "\n\n" : "") + (event.text ?? ""),
            status: undefined,
          }));
        } else if (event.type === "tool_call") {
          updateReply((turn) => ({ ...turn, status: TOOL_STATUS[event.tool ?? ""] ?? "Working" }));
        } else if (event.type === "error") {
          updateReply((turn) => ({ ...turn, status: undefined, error: event.text ?? "Something went wrong." }));
        } else if (event.type === "done") {
          updateReply((turn) => ({ ...turn, status: undefined, quickReplies: quickRepliesFrom(event) }));
        }
      }, controller.signal);
    } catch {
      if (controller.signal.aborted) return;
      if (assistantId === null) {
        setSendError("We couldn't restore your planning session. Check your connection and send it again.");
      } else {
        updateReply((turn) => ({
          ...turn,
          status: undefined,
          error: "We couldn't reach the assistant. Check your connection and send it again.",
        }));
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setBusy(false);
      }
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  }

  // Quick replies belong to the question just asked: only the latest turn shows them.
  const lastTurn = turns[turns.length - 1];
  const quickReplies = !busy && lastTurn?.role === "assistant" ? lastTurn.quickReplies : undefined;

  return (
    <section aria-label="Chat" className="flex flex-col gap-5">
      {turns.length > 0 && (
        <ol aria-live="polite" className="flex flex-col gap-4">
          {turns.map((t) =>
            t.role === "student" ? (
              <li key={t.id} className="self-end rounded-card bg-field px-4 py-2.5 max-w-[60ch]">
                <span className="sr-only">You: </span>
                {t.text}
              </li>
            ) : (
              <li key={t.id} className="flex max-w-[65ch] flex-col gap-2">
                <span className="sr-only">Assistant: </span>
                {t.text && <p className="whitespace-pre-wrap">{t.text}</p>}
                {t.status && (
                  <p role="status" className="flex items-center gap-2 text-sm text-muted">
                    <LoaderCircle
                      size={14}
                      strokeWidth={ICON_STROKE}
                      aria-hidden="true"
                      className="motion-safe:animate-spin"
                    />
                    {t.status}
                  </p>
                )}
                {t.error && (
                  <p role="alert" className="flex items-start gap-2 text-sm">
                    <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
                    {t.error}
                  </p>
                )}
              </li>
            ),
          )}
        </ol>
      )}

      {quickReplies && (
        <ul aria-label="Quick replies" className="flex flex-wrap gap-2">
          {quickReplies.map((option) => (
            <li key={option}>
              <button
                type="button"
                onClick={() => void send(option)}
                className="min-h-11 rounded-btn border border-line bg-surface px-4 text-[15px] text-ink transition-colors duration-150 hover:bg-field"
              >
                {option}
              </button>
            </li>
          ))}
        </ul>
      )}

      {sendError && <p role="alert" className="text-sm">{sendError}</p>}
      <form
        onSubmit={onSubmit}
        className="chat-composer rounded-card border border-line bg-surface shadow-[0_0_0_6px_var(--halo)] transition-colors duration-150 focus-within:border-ink"
      >
        <label htmlFor={inputId} className="sr-only">
          Tell the assistant what you want in your schedule
        </label>
        <textarea
          id={inputId}
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="No classes before 10, Fridays off, 12 to 15 credits"
          className="block w-full resize-none rounded-t-card bg-transparent px-5 pt-4 text-[17px] outline-none placeholder:text-muted"
        />
        <div className="flex items-center justify-between px-4 pb-3">
          <Link to="/consent" className="inline-flex min-h-11 items-center gap-2 rounded-btn border border-line px-3 text-[13px] hover:bg-field"><Plus size={16} aria-hidden="true" />Add degree audit</Link>
          <button
            type="submit"
            aria-label={busy ? "Sending" : "Send"}
            disabled={busy || !draft.trim()}
            className="grid size-11 place-items-center rounded-btn bg-ink text-surface transition-colors duration-150 hover:bg-[#333] disabled:bg-[#9b978f]"
          >
            {busy ? (
              <LoaderCircle
                size={18}
                strokeWidth={ICON_STROKE}
                aria-hidden="true"
                className="motion-safe:animate-spin"
              />
            ) : (
              <ArrowUp size={18} strokeWidth={ICON_STROKE} aria-hidden="true" />
            )}
          </button>
        </div>
      </form>

      <p className="chat-audit-hint text-center text-[13px] text-muted">No audit yet? <Link to="/consent" className="text-ink underline underline-offset-2">Try the sample audit</Link></p>
      {turns.length === 0 && (
        <ul aria-label="Suggestions" className="chat-starters flex flex-wrap justify-center gap-x-7 gap-y-2 pt-8 md:pt-10">
          {STARTERS.map((s, i) => (
            <li key={s.label}>
              <button
                type="button"
                onClick={() => setDraft(s.text)}
                className="flex min-h-11 items-center gap-2 font-serif text-[19px] text-ink transition-colors duration-150 hover:text-ink"
              >
                <span aria-hidden="true" className={`size-4 rounded-[4px] ${STARTER_COLORS[i]}`} />
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
