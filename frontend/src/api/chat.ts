import { ApiError, apiBaseUrl } from "./client";
import type { ChatEvent } from "./schemas";

/**
 * Sends one chat message (`POST /api/chat`) and calls `onEvent` for every
 * server-sent event as it arrives. Resolves after the stream ends.
 * The Claude API key never reaches the browser: only our backend talks to Claude.
 */
export async function streamChat(
  message: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await globalThis.fetch(`${apiBaseUrl()}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok || !response.body) throw new ApiError(response.status);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    // Events are separated by a blank line; each has one `data:` line of JSON.
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const raw = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = raw
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("");
      if (data) onEvent(JSON.parse(data) as ChatEvent);
      end = buffer.indexOf("\n\n");
    }
    if (done) return;
  }
}
