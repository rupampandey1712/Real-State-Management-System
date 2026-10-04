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
  commentSent?: boolean;
}

const stripMarkers = (text: string) => text.replace(/\s*\[[SD]\d+\]/g, "");

/** A citation you can open (FR-5.2): shows the field's value or the document passage the answer used. */
function Sources({ citations, onShowFact }: { citations: Citation[]; onShowFact: (label: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const current = citations.find((c) => c.id === open);
  return (
    <div className="mt-2">
      <ul className="flex flex-wrap gap-1.5" aria-label="Sources">
        {citations.map((c) => (
          <li key={c.id}>
            <button type="button" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}
              className={`rounded px-1.5 text-sm font-semibold text-ink ${open === c.id ? "bg-haldi" : "bg-haldi-wash hover:bg-haldi/60"}`}>
              {c.type === "document" ? c.label : `Listing: ${c.label}`}
            </button>
          </li>
        ))}
      </ul>
      {current && (
        <div className="mt-2 rounded-md border border-rule bg-wash p-3 text-[0.95rem]">
          <p className="text-sm font-semibold text-slate">{current.type === "document" ? `From ${current.label}` : `From the listing: ${current.label}`}</p>
          {current.excerpt && <p className="mt-1 whitespace-pre-line">{current.type === "document" ? `“${current.excerpt}”` : current.excerpt}</p>}
          {current.type === "listing_field" && (
            <button type="button" onClick={() => onShowFact(current.label)} className="link mt-1 text-sm">Show it in the listing</button>
          )}
        </div>
      )}
    </div>
  );
}

function Rating({ turn, onRate, onComment }: {
  turn: Turn; onRate: (rating: 1 | -1) => void; onComment: (comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  if (!turn.requestId) return null;
  return (
    <div className="w-full space-y-2">
      <span className="flex gap-3" role="group" aria-label="Was this answer helpful?">
        <button disabled={!!turn.rated} onClick={() => onRate(1)} className={turn.rated === 1 ? "font-semibold text-leaf" : "hover:text-ink"}>
          {turn.rated === 1 ? "Marked helpful" : "Helpful"}
        </button>
        <button disabled={!!turn.rated} onClick={() => onRate(-1)} className={turn.rated === -1 ? "font-semibold text-danger" : "hover:text-ink"}>
          {turn.rated === -1 ? "Marked not helpful" : "Not helpful"}
        </button>
      </span>
      {turn.rated && !turn.commentSent && (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (comment.trim()) onComment(comment.trim()); }}>
          <label className="sr-only" htmlFor={`comment-${turn.requestId}`}>Tell us more (optional)</label>
          <input id={`comment-${turn.requestId}`} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000}
            placeholder={turn.rated === -1 ? "What was wrong? (optional)" : "Anything to add? (optional)"} className="field py-1 text-sm" />
          <button disabled={!comment.trim()} className="btn-quiet py-1 text-sm">Send</button>
        </form>
      )}
      {turn.commentSent && <span className="text-sm text-leaf" role="status">Thanks, that helps us improve.</span>}
    </div>
  );
}

export default function QAPanel({ listingId, onAskAgent, onShowFact }: {
  listingId: string; onAskAgent: (question: string) => void; onShowFact: (label: string) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { data: suggestions } = useQuery({
    queryKey: ["qa-suggestions", listingId],
    queryFn: () => api<{ suggestions: string[] }>(`/listings/${listingId}/qa/suggestions`),
  });

  const update = (fn: (turn: Turn) => Turn) => setTurns((t) => [...t.slice(0, -1), fn(t[t.length - 1])]);
  const patchTurn = (index: number, changes: Partial<Turn>) => setTurns((t) => t.map((x, i) => (i === index ? { ...x, ...changes } : x)));

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
    patchTurn(index, { rated: rating });
    await post("/ai/feedback", { ai_request_id: turn.requestId, rating }).catch(() => undefined);
  };

  const comment = async (index: number, text: string) => {
    const turn = turns[index];
    if (!turn.requestId || !turn.rated) return;
    patchTurn(index, { commentSent: true });
    await post("/ai/feedback", { ai_request_id: turn.requestId, rating: turn.rated, comment: text }).catch(() => undefined);
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
        <p className="mt-1 text-sm font-medium text-ink">AI answers can be incomplete — verify with the agent.</p>
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
                {turn.citations.length > 0 && <Sources citations={turn.citations} onShowFact={onShowFact} />}
                {turn.status && turn.status !== "error" && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate">
                    {(turn.status === "unknown" || turn.status === "unverified") && (
                      <button onClick={() => onAskAgent(turn.question)} className="link text-sm">Ask the agent instead</button>
                    )}
                    {turn.status === "unverified" && <span>We couldn't match this answer to the listing. Check with the agent.</span>}
                    <Rating turn={turn} onRate={(r) => rate(i, r)} onComment={(c) => comment(i, c)} />
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
