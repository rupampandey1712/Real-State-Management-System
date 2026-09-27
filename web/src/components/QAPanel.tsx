import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { api, post } from "../lib/api";
import { postSSE } from "../lib/sse";
import type { Citation } from "../lib/types";

interface Turn {
  question: string;
  answer: string;
  citations: Citation[];
  status?: string; // answered | unknown | unverified | refused | error
  requestId?: string | null;
  rated?: 1 | -1;
}

const stripMarkers = (text: string) => text.replace(/\s*\[[SD]\d+\]/g, "");

export default function QAPanel({ listingId, onAskAgent }: { listingId: string; onAskAgent: (question: string) => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { data: suggestions } = useQuery({
    queryKey: ["qa-suggestions", listingId],
    queryFn: () => api<{ suggestions: string[] }>(`/listings/${listingId}/qa/suggestions`),
  });

  const update = (fn: (turn: Turn) => Turn) => setTurns((t) => [...t.slice(0, -1), fn(t[t.length - 1])]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    const history = turns.flatMap((t) => [
      { role: "user", content: t.question },
      { role: "assistant", content: t.answer },
    ]);
    setTurns((t) => [...t, { question, answer: "", citations: [] }]);
    setInput("");
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      for await (const { event, data } of postSSE(`/listings/${listingId}/qa`, { question, history }, abortRef.current.signal)) {
        const payload = data as Record<string, unknown>;
        if (event === "token") update((t) => ({ ...t, answer: t.answer + (payload.text as string) }));
        if (event === "citations") update((t) => ({ ...t, citations: payload.sources as Citation[] }));
        if (event === "done") update((t) => ({ ...t, status: payload.answer_status as string, requestId: payload.ai_request_id as string | null }));
        if (event === "error") update((t) => ({ ...t, answer: payload.message as string, status: "error" }));
      }
    } catch {
      update((t) => ({ ...t, answer: "The assistant couldn't answer just now. You can still contact the agent below.", status: "error" }));
    } finally {
      setBusy(false);
    }
  };

  const rate = async (index: number, rating: 1 | -1) => {
    const turn = turns[index];
    if (!turn.requestId) return;
    setTurns((t) => t.map((x, i) => (i === index ? { ...x, rated: rating } : x)));
    await post("/ai/feedback", { ai_request_id: turn.requestId, rating }).catch(() => undefined);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void ask(input);
  };

  return (
    <section className="rounded-lg border border-rule bg-paper" aria-labelledby="qa-heading">
      <div className="border-b border-rule px-5 py-4">
        <h2 id="qa-heading" className="text-xl font-bold">Ask about this home</h2>
        <p className="text-[0.95rem] text-slate">Answers come only from this listing and its documents.</p>
      </div>

      <div className="max-h-[28rem] space-y-6 overflow-y-auto px-5 py-5" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {(suggestions?.suggestions ?? []).map((s) => (
              <button key={s} onClick={() => ask(s)} className="rounded-md border border-rule px-3 py-1.5 text-left text-[0.95rem] hover:border-ink">
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((turn, i) => {
          const streaming = busy && i === turns.length - 1;
          return (
            <div key={i}>
              <p className="text-right font-semibold text-ink">{turn.question}</p>
              <div className={`mt-2 border-l-2 pl-4 ${turn.status === "error" ? "border-danger" : "border-haldi"}`}>
                <p className={streaming ? "streaming-caret" : ""}>{stripMarkers(turn.answer)}</p>
                {turn.citations.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Sources">
                    {turn.citations.map((c) => (
                      <li key={c.id} className="rounded bg-haldi-wash px-1.5 text-sm font-semibold text-ink">
                        {c.type === "document" ? c.label : `Listing: ${c.label}`}
                      </li>
                    ))}
                  </ul>
                )}
                {turn.status && turn.status !== "error" && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate">
                    {turn.status === "unknown" && (
                      <button onClick={() => onAskAgent(turn.question)} className="link text-sm">Ask the agent instead</button>
                    )}
                    {turn.status === "unverified" && <span>We couldn't match this answer to the listing. Check with the agent.</span>}
                    {turn.requestId && (
                      <span className="flex gap-3">
                        <button disabled={!!turn.rated} onClick={() => rate(i, 1)} className={turn.rated === 1 ? "font-semibold text-leaf" : "hover:text-ink"}>
                          {turn.rated === 1 ? "Marked helpful" : "Helpful"}
                        </button>
                        <button disabled={!!turn.rated} onClick={() => rate(i, -1)} className={turn.rated === -1 ? "font-semibold text-danger" : "hover:text-ink"}>
                          {turn.rated === -1 ? "Marked not helpful" : "Not helpful"}
                        </button>
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-rule p-4">
        <label htmlFor="qa-input" className="sr-only">Your question</label>
        <input
          id="qa-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={1000}
          placeholder="Is the society okay with pets?"
          className="field"
        />
        <button disabled={busy || !input.trim()} className="btn-primary">Ask</button>
      </form>
    </section>
  );
}
