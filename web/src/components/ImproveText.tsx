import { useState } from "react";

import { post } from "../lib/api";
import type { ImproveResponse } from "../lib/types";

type Tone = "professional" | "warm" | "luxury";

/** FR-4.4: rewrite the agent's own description in a chosen tone. Nothing changes until they use it. */
export default function ImproveText({ listingId, text, onAccept }: {
  listingId: string; text: string; onAccept: (description: string) => void;
}) {
  const [tone, setTone] = useState<Tone>("professional");
  const [result, setResult] = useState<ImproveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tooShort = text.trim().length < 20;

  const improve = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await post<ImproveResponse>("/ai/improve", { listing_id: listingId, text, tone }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-rule bg-paper p-5" aria-labelledby="improve-heading">
      <div>
        <h2 id="improve-heading" className="text-xl font-bold">Improve my text</h2>
        <p className="text-[0.95rem] text-slate">Rewrites the description you wrote, in the tone you pick. It keeps your facts and adds none.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="field-label">Tone
          <select value={tone} onChange={(e) => setTone(e.target.value as Tone)} className="field mt-1 w-auto">
            <option value="professional">Professional</option>
            <option value="warm">Warm</option>
            <option value="luxury">Luxury</option>
          </select>
        </label>
        <button type="button" onClick={improve} disabled={busy || tooShort} className="btn-quiet">
          {busy ? "Rewriting…" : "Rewrite my description"}
        </button>
      </div>
      {tooShort && <p className="text-sm text-slate">Write at least a sentence in the description first.</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}
      {result && (
        <div className="space-y-3 border-t border-rule pt-3">
          {result.warnings.length > 0 && (
            <div className="rounded-md bg-haldi-wash p-3 text-[0.95rem]">
              <p className="font-semibold">Check these before using it</p>
              <ul className="mt-1 list-disc pl-5">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </div>
          )}
          <label className="field-label">Rewritten description
            <textarea value={result.description} onChange={(e) => setResult({ ...result, description: e.target.value })} rows={7} className="field mt-1" />
          </label>
          <div className="flex gap-3">
            <button type="button" onClick={() => { onAccept(result.description); setResult(null); }} className="btn-quiet">Use this version</button>
            <button type="button" onClick={() => setResult(null)} className="text-sm font-medium text-slate hover:text-ink">Discard</button>
          </div>
        </div>
      )}
    </section>
  );
}
