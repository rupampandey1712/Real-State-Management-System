import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../lib/api";
import type { AIMetricRow } from "../../lib/types";

interface ProductMetrics {
  days: number;
  searches: number;
  nl_search_share: number | null;
  ctr_nl: number | null;
  ctr_classic: number | null;
  ctr_lift: number | null;
  listings_published: number;
  median_minutes_to_publish: number | null;
  ai_descriptions_saved: number;
  ai_descriptions_light_edit_share: number | null;
  qa_sessions: number;
  qa_without_agent_contact: number | null;
}

type AIMetrics = { rows: AIMetricRow[] };

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

/** Requirements §9: one row per success metric with its target and status (icon + word, never colour alone). */
function Metric({ label, value, target, met, basis }: { label: string; value: string; target: string; met: boolean | null; basis: string }) {
  return (
    <tr className="border-t border-rule">
      <th scope="row" className="py-3 pr-4 text-left font-semibold">{label}</th>
      <td className="py-3 pr-4 text-2xl font-bold tabular-nums">{value}</td>
      <td className="py-3 pr-4 text-slate">{target}</td>
      <td className="py-3 pr-4">
        {met === null ? <span className="text-slate">– Not enough data</span>
          : met ? <span className="font-semibold text-leaf">✓ On target</span>
          : <span className="font-semibold text-danger">✗ Below target</span>}
      </td>
      <td className="py-3 text-sm text-slate">{basis}</td>
    </tr>
  );
}

export default function SuccessMetrics() {
  const [days, setDays] = useState(60);
  const product = useQuery({ queryKey: ["admin-product-metrics", days], queryFn: () => api<ProductMetrics>(`/admin/product-metrics?days=${days}`) });
  // The AI request log keeps 30 days, so the 👍 ratio covers at most the last 30.
  const ai = useQuery({ queryKey: ["admin-ai-metrics", 30], queryFn: () => api<AIMetrics>("/admin/ai/metrics?days=30") });
  const p = product.data;
  const qaRows = ai.data?.rows.filter((r) => r.feature === "qa") ?? [];
  const up = qaRows.reduce((n, r) => n + r.thumbs_up, 0);
  const down = qaRows.reduce((n, r) => n + r.thumbs_down, 0);
  const answers = qaRows.reduce((n, r) => n + r.requests, 0);
  const thumbsRatio = up + down ? up / (up + down) : null;
  const errorsPerThousand = answers ? (down / answers) * 1000 : null;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold">Success metrics</h2>
        <label className="flex items-center gap-2 text-[0.95rem] text-slate">Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="field w-auto py-1">
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={60}>Last 60 days</option><option value={90}>Last 90 days</option>
          </select>
        </label>
      </div>
      <p className="max-w-prose text-sm text-slate">
        From anonymous product events (no user ids or personal details) and the AI request log. Targets are from the
        requirements and are measured 60 days after launch.
      </p>
      {product.isLoading && <p className="text-slate">Loading…</p>}
      {product.isError && <p className="text-danger" role="alert">{(product.error as Error).message}</p>}
      {p && (
        <div className="overflow-x-auto rounded-lg border border-rule bg-paper px-5">
          <table className="w-full">
            <thead className="text-left text-sm text-slate">
              <tr><th className="py-2 font-medium">Metric</th><th className="py-2 font-medium">Now</th><th className="py-2 font-medium">Target</th><th className="py-2 font-medium">Status</th><th className="py-2 font-medium">Based on</th></tr>
            </thead>
            <tbody>
              <Metric label="Search → listing view, NL vs classic" value={p.ctr_lift === null ? "—" : `${p.ctr_lift >= 0 ? "+" : ""}${Math.round(p.ctr_lift * 100)}%`}
                target="+20%" met={p.ctr_lift === null ? null : p.ctr_lift >= 0.2}
                basis={`NL ${pct(p.ctr_nl)} vs classic ${pct(p.ctr_classic)} click-through`} />
              <Metric label="Searches using the NL box" value={pct(p.nl_search_share)} target="≥ 40%"
                met={p.nl_search_share === null ? null : p.nl_search_share >= 0.4} basis={`${p.searches} searches`} />
              <Metric label="Median agent time to publish" value={p.median_minutes_to_publish === null ? "—" : `${p.median_minutes_to_publish} min`}
                target="≤ 10 min" met={p.median_minutes_to_publish === null ? null : p.median_minutes_to_publish <= 10}
                basis={`${p.listings_published} first publishes (from creating the draft)`} />
              <Metric label="AI descriptions kept with ≤ 20% edits" value={pct(p.ai_descriptions_light_edit_share)} target="≥ 60%"
                met={p.ai_descriptions_light_edit_share === null ? null : p.ai_descriptions_light_edit_share >= 0.6}
                basis={`${p.ai_descriptions_saved} saved AI drafts`} />
              <Metric label="Q&A 👍 ratio" value={pct(thumbsRatio)} target="≥ 80%" met={thumbsRatio === null ? null : thumbsRatio >= 0.8}
                basis={`${up} 👍 · ${down} 👎, last 30 days`} />
              <Metric label="Q&A without contacting the agent" value={pct(p.qa_without_agent_contact)} target="≥ 50%"
                met={p.qa_without_agent_contact === null ? null : p.qa_without_agent_contact >= 0.5}
                basis={`${p.qa_sessions} Q&A sessions`} />
              <Metric label="Reported AI answer problems" value={errorsPerThousand === null ? "—" : `${errorsPerThousand.toFixed(1)} / 1,000`}
                target="< 1 / 1,000 (factual errors)" met={errorsPerThousand === null ? null : errorsPerThousand < 1}
                basis="👎 per answer — an upper bound; review them on the AI tab" />
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
