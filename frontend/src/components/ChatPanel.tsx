import { LoaderCircle, Send } from "lucide-react";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { streamChat } from "../api/chat";
import type { ChatEvent } from "../api/schemas";
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

interface Turn {
  id: number;
  role: "student" | "assistant";
  text: string;
  status?: string;
  error?: string;
}

interface ChatPanelProps {
  /** Every event, so the page can show chips and schedule cards. */
  onEvent?: (event: ChatEvent) => void;
}

export function ChatPanel({ onEvent }: ChatPanelProps) {
  const inputId = useId();
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(0);
  const lastEvent = useRef<ChatEvent["type"] | null>(null);

  const updateLast = (patch: (t: Turn) => Turn) =>
    setTurns((all) => [...all.slice(0, -1), patch(all[all.length - 1] as Turn)]);

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy) return;
    setDraft("");
    setBusy(true);
    setTurns((all) => [
      ...all,
      { id: nextId.current++, role: "student", text },
      { id: nextId.current++, role: "assistant", text: "" },
    ]);
    lastEvent.current = null;
    try {
      await streamChat(text, (event) => {
        onEvent?.(event);
        const afterTool = lastEvent.current === "tool_result" || lastEvent.current === "tool_call";
        lastEvent.current = event.type;
        if (event.type === "text") {
          // Text from a new step after a tool runs starts a new paragraph.
          updateLast((t) => ({
            ...t,
            text: t.text + (afterTool && t.text ? "\n\n" : "") + (event.text ?? ""),
            status: undefined,
          }));
        } else if (event.type === "tool_call") {
          updateLast((t) => ({ ...t, status: TOOL_STATUS[event.tool ?? ""] ?? "Working" }));
        } else if (event.type === "error") {
          updateLast((t) => ({ ...t, status: undefined, error: event.text ?? "Something went wrong." }));
        } else if (event.type === "done") {
          updateLast((t) => ({ ...t, status: undefined }));
        }
      });
    } catch {
      updateLast((t) => ({
        ...t,
        status: undefined,
        error: "We couldn't reach the assistant. Check your connection and send it again.",
      }));
    } finally {
      setBusy(false);
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

      <form
        onSubmit={onSubmit}
        className="rounded-card border border-line bg-surface shadow-[0_0_0_6px_var(--halo)] transition-colors duration-150 focus-within:border-ink"
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
        <div className="flex justify-end px-3 pb-3">
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
              <Send size={18} strokeWidth={ICON_STROKE} aria-hidden="true" />
            )}
          </button>
        </div>
      </form>

      {turns.length === 0 && (
        <ul aria-label="Suggestions" className="flex flex-wrap justify-center gap-x-5 gap-y-2">
          {STARTERS.map((s, i) => (
            <li key={s.label}>
              <button
                type="button"
                onClick={() => setDraft(s.text)}
                className="flex min-h-11 items-center gap-2 font-serif text-[17px] text-muted transition-colors duration-150 hover:text-ink"
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
