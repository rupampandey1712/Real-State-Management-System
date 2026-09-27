import { useState } from "react";

import { post } from "../lib/api";
import type { DescribeResponse } from "../lib/types";

interface Props {
  listingId: string;
  onAccept: (draft: { title: string; description: string }) => void;
}

function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: [T, string][]; onChange: (v: T) => void;
}) {
  return (
    <fieldset>
      <legend className="field-label mb-1">{label}</legend>
      <div className="inline-flex rounded-md border border-rule bg-wash p-0.5">
        {options.map(([v, text]) => (
          <label key={v} className={`cursor-pointer rounded px-3 py-1 text-[0.95rem] ${value === v ? "bg-paper font-semibold text-ink shadow-[0_0_0_1px_var(--color-rule)]" : "text-slate"}`}>
            <input type="radio" className="sr-only" name={label} value={v} checked={value === v} onChange={() => onChange(v)} />
            {text}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** FR-4: write a draft → edit → explicitly use it. Nothing is saved until the agent saves the listing. */
export default function DescriptionGenerator({ listingId, onAccept }: Props) {
  const [tone, setTone] = useState<"professional" | "warm" | "luxury">("warm");
  const [length, setLength] = useState<"short" | "medium" | "long">("medium");
  const [notes, setNotes] = useState("");
  const [draft, setDraft] = useState<DescribeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setDraft(await post<DescribeResponse>("/ai/describe", { listing_id: listingId, tone, length, agent_notes: notes }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-4 rounded-lg border border-rule bg-paper p-5" aria-labelledby="ai-desc">
      <div>
        <h2 id="ai-desc" className="text-xl font-bold">Draft the description</h2>
        <p className="text-[0.95rem] text-slate">Written only from the details you've saved. You review it before anything goes live.</p>
      </div>
      <div className="flex flex-wrap gap-4">
        <Segmented label="Tone" value={tone} onChange={setTone} options={[["professional", "Professional"], ["warm", "Warm"], ["luxury", "Luxury"]]} />
        <Segmented label="Length" value={length} onChange={setLength} options={[["short", "Short"], ["medium", "Medium"], ["long", "Long"]]} />
      </div>
      <label className="field-label">Anything else to mention? (facts only)
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} rows={2}
          className="field mt-1" placeholder="Recently repainted. The society has EV charging." />
      </label>
      <button onClick={generate} disabled={busy} className="btn-primary">
        {busy ? "Writing…" : draft ? "Write another draft" : "Write a draft"}
      </button>
      {error && <p className="text-danger" role="alert">{error}</p>}

      {draft && (
        <div className="space-y-3 border-t border-rule pt-4">
          {draft.warnings.length > 0 && (
            <div className="rounded-md bg-haldi-wash p-3 text-[0.95rem]">
              <p className="font-semibold">Check these before using the draft</p>
              <ul className="mt-1 list-disc pl-5">{draft.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </div>
          )}
          <label className="field-label">Title
            <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="field mt-1 font-semibold" />
          </label>
          <label className="field-label">Description
            <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={7} className="field mt-1" />
          </label>
          <div>
            <p className="field-label">Highlights</p>
            <ul className="mt-1 list-disc pl-5">{draft.highlights.map((h) => <li key={h}>{h}</li>)}</ul>
          </div>
          <button onClick={() => onAccept({ title: draft.title, description: draft.description })} className="btn-quiet">
            Use this draft
          </button>
        </div>
      )}
    </section>
  );
}
