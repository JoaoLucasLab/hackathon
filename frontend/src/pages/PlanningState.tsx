import {
  createContext, useContext, useEffect, useRef, useState,
  type ReactNode, type Dispatch, type SetStateAction, type MutableRefObject,
} from "react";
import type { ConstraintSet, Relaxation, Schedule } from "../api/schemas";

export interface Results {
  constraints: ConstraintSet;
  schedules: Schedule[];
  relaxation?: Relaxation | null;
}

export interface ChatTurn {
  id: number;
  role: "student" | "assistant";
  text: string;
  status?: string;
  error?: string;
  /** Fixed answers to the assistant's question (AI-07). Shown on the latest turn only. */
  quickReplies?: string[];
}

const Context = createContext<{
  results: Results | null;
  setResults: Dispatch<SetStateAction<Results | null>>;
  draft: string;
  setDraft: Dispatch<SetStateAction<string>>;
  turns: ChatTurn[];
  setTurns: Dispatch<SetStateAction<ChatTurn[]>>;
  busy: boolean;
  setBusy: Dispatch<SetStateAction<boolean>>;
  sendError: string | null;
  setSendError: Dispatch<SetStateAction<string | null>>;
  nextTurnId: MutableRefObject<number>;
  activeRequest: MutableRefObject<AbortController | null>;
  clearChat: () => void;
} | null>(null);

// This provider outlives route changes. Student data stays in memory only.
export function PlanningState({ children }: { children: ReactNode }) {
  const [results, setResults] = useState<Results | null>(null);
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const nextTurnId = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  function clearChat() {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setTurns([]);
    setBusy(false);
    setSendError(null);
  }

  return (
    <Context.Provider value={{
      results, setResults, draft, setDraft, turns, setTurns, busy, setBusy,
      sendError, setSendError, nextTurnId, activeRequest, clearChat,
    }}>
      {children}
    </Context.Provider>
  );
}

export function usePlanningState() {
  const state = useContext(Context);
  if (!state) throw new Error("PlanningState is required");
  return state;
}
