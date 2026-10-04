import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, download, put } from "../../lib/api";
import type { AIMetricRow, FeedbackItem, FlagState } from "../../lib/types";

type FlagMap = Record<string, FlagState>;

const FEATURES = ["nl_search", "describe", "improve", "qa"] as const;
const FEATURE_LABEL: Record<string, string> = { nl_search: "NL search", describe: "Descriptions", improve: "Improve my text", qa: "Listing Q&A" };
const usd = (n: number) => `$${n < 1 ? n.toFixed(4) : n.toFixed(2)}`;

/** One feature's daily request counts: a single-series bar chart (one hue, no legend), oldest → newest. */
function DailyBars({ rows, days }: { rows: AIMetricRow[]; days: string[] }) {
  const byDay = new Map(rows.map((r) => [r.day, r]));
  const max = Math.max(1, ...rows.map((r) => r.requests));
  return (
    <div className="flex h-16 items-end gap-0.5" role="img" aria-label={`Daily requests: ${days.map((d) => `${d} ${byDay.get(d)?.requests ?? 0}`).join(", ")}`}>
      {days.map((day) => {
        const row = byDay.get(day);
        const h = row ? Math.max(4, (row.requests / max) * 64) : 0;
        return (
          <div key={day} className="group relative flex h-full flex-1 items-end">
            <div className="w-full rounded-t-[4px] bg-ink" style={{ height: h }} />
            <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-ink px-2 py-1 text-xs text-paper group-hover:block">
              {day}: {row?.requests ?? 0} requests{row ? `, ${(row.error_rate * 100).toFixed(1)}% errors` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <p className="text-sm text-slate">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-ink">{value}</p>
      {note && <p className="text-xs text-slate">{note}</p>}
    </div>
  );
}

function Metrics() {
  const [days, setDays] = useState(14);
  const { data, isLoading } = useQuery({
    queryKey: ["admin-ai-metrics", days],
    queryFn: () => api<{ days: number; logging_enabled: boolean; rows: AIMetricRow[] }>(`/admin/ai/metrics?days=${days}`),
  });
  const rows = data?.rows ?? [];
  const dayList = Array.from({ length: days }, (_, i) => new Date(Date.now() - (days - 1 - i) * 86_400_000).toISOString().slice(0, 10));

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold">AI usage and quality</h2>
        <label className="flex items-center gap-2 text-[0.95rem] text-slate">Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="field w-auto py-1">
            <option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option>
          </select>
        </label>
      </div>
      {isLoading && <p className="text-slate">Loading…</p>}
      {data && !data.logging_enabled && <p className="text-danger">AI request logging is not configured (Cosmos DB), so there is nothing to show.</p>}
      <div className="grid gap-6 lg:grid-cols-2">
        {FEATURES.map((feature) => {
          const fr = rows.filter((r) => r.feature === feature);
          const requests = fr.reduce((n, r) => n + r.requests, 0);
          const errors = fr.reduce((n, r) => n + r.errors, 0);
          const cost = fr.reduce((n, r) => n + r.cost_usd, 0);
          const up = fr.reduce((n, r) => n + r.thumbs_up, 0);
          const down = fr.reduce((n, r) => n + r.thumbs_down, 0);
          const p95 = Math.max(0, ...fr.map((r) => r.latency_p95_ms ?? 0));
          return (
            <div key={feature} className="space-y-3 rounded-lg border border-rule bg-paper p-5">
              <h3 className="text-lg font-bold">{FEATURE_LABEL[feature]}</h3>
              <div className="grid grid-cols-3 gap-4">
                <Tile label="Requests" value={requests.toLocaleString("en-IN")} />
                <Tile label="Error rate" value={requests ? `${((errors / requests) * 100).toFixed(1)}%` : "—"} />
                <Tile label="Cost" value={usd(cost)} note={requests ? `${usd(cost / requests)} a request` : undefined} />
                <Tile label="Worst daily p95" value={p95 ? `${(p95 / 1000).toFixed(1)} s` : "—"} />
                <Tile label="Helpful" value={up + down ? `${Math.round((up / (up + down)) * 100)}%` : "—"} note={`${up} 👍 · ${down} 👎`} />
              </div>
              <DailyBars rows={fr} days={dayList} />
            </div>
          );
        })}
      </div>
      <details className="rounded-lg border border-rule bg-paper p-4">
        <summary className="cursor-pointer font-semibold">Table view (per feature, per day)</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className="text-left text-slate">
              <tr>{["Day", "Feature", "Requests", "Errors", "Input tokens", "Output tokens", "Cost", "p50", "p95", "👍", "👎"].map((h) => <th key={h} className="px-2 py-1 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.day}-${r.feature}`} className="border-t border-rule">
                  <td className="px-2 py-1">{r.day}</td><td className="px-2 py-1">{FEATURE_LABEL[r.feature] ?? r.feature}</td>
                  <td className="px-2 py-1">{r.requests}</td><td className="px-2 py-1">{r.errors}</td>
                  <td className="px-2 py-1">{r.input_tokens.toLocaleString("en-IN")}</td><td className="px-2 py-1">{r.output_tokens.toLocaleString("en-IN")}</td>
                  <td className="px-2 py-1">{usd(r.cost_usd)}</td><td className="px-2 py-1">{r.latency_p50_ms ?? "—"} ms</td>
                  <td className="px-2 py-1">{r.latency_p95_ms ?? "—"} ms</td><td className="px-2 py-1">{r.thumbs_up}</td><td className="px-2 py-1">{r.thumbs_down}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function Feedback() {
  const [feature, setFeature] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["admin-ai-feedback", feature],
    queryFn: () => api<FeedbackItem[]>(`/admin/ai/feedback?rating=-1${feature ? `&feature=${feature}` : ""}`),
  });
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold">Answers people marked not helpful</h2>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-[0.95rem] text-slate">Feature
            <select value={feature} onChange={(e) => setFeature(e.target.value)} className="field w-auto py-1">
              <option value="">All</option>
              {FEATURES.map((f) => <option key={f} value={f}>{FEATURE_LABEL[f]}</option>)}
            </select>
          </label>
          <button className="btn-quiet" onClick={() => download(`/admin/ai/feedback/export${feature ? `?feature=${feature}` : ""}`, `eval-candidates-${feature || "all"}.jsonl`).catch((e) => setError((e as Error).message))}>
            Export as eval cases
          </button>
        </div>
      </div>
      <p className="text-sm text-slate">Text was stripped of emails, phone numbers and ID numbers when it was logged. Review exported cases before adding them to an eval suite.</p>
      {error && <p className="text-danger" role="alert">{error}</p>}
      {isLoading && <p className="text-slate">Loading…</p>}
      {data?.length === 0 && <p className="text-slate">Nothing marked not helpful in the last 30 days.</p>}
      <ul className="space-y-3">
        {data?.map((item) => (
          <li key={item.id} className="space-y-2 rounded-lg border border-rule bg-paper p-4">
            <p className="text-sm text-slate">
              {FEATURE_LABEL[item.feature] ?? item.feature} · {new Date(item.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} · {item.prompt_id}.v{item.prompt_version} · {item.model}
              {item.listing_id && <> · <Link to={`/listings/${item.listing_id}`} className="link text-sm">listing</Link></>}
            </p>
            <p className="whitespace-pre-line text-[0.95rem]"><span className="font-semibold">Asked: </span>{item.request_redacted?.slice(-600)}</p>
            <p className="whitespace-pre-line text-[0.95rem]"><span className="font-semibold">Answered: </span>{item.response_redacted}</p>
            {item.feedback_comment && <p className="text-[0.95rem]"><span className="font-semibold">Their comment: </span>{item.feedback_comment}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Flags() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin-ai-flags"], queryFn: () => api<FlagMap>("/admin/ai/flags") });
  const change = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean | null }) => put<FlagState>(`/admin/ai/flags/${name}`, { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-ai-flags"] });
      void queryClient.invalidateQueries({ queryKey: ["ai-features"] });
    },
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-bold">AI features on or off</h2>
      <p className="text-sm text-slate">Changes reach every server within a few seconds. Switched-off features fall back to the non-AI behaviour.</p>
      <ul>
        {data && Object.entries(data).map(([name, flag]) => (
          <li key={name} className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-rule py-3 last:border-b">
            <label className="flex min-w-0 flex-1 items-start gap-3">
              <input type="checkbox" checked={flag.enabled} disabled={change.isPending} className="mt-1.5 size-4 accent-ink"
                onChange={(e) => change.mutate({ name, enabled: e.target.checked })} />
              <span>
                <span className="font-semibold">{name.replace(/_/g, " ")}</span> <span className={flag.enabled ? "text-leaf" : "text-danger"}>{flag.enabled ? "On" : "Off"}</span>
                <span className="block text-sm text-slate">{flag.description}</span>
              </span>
            </label>
            {flag.overridden && (
              <button onClick={() => change.mutate({ name, enabled: null })} className="text-sm font-medium text-slate hover:text-ink">
                Reset to default ({flag.default ? "on" : "off"})
              </button>
            )}
          </li>
        ))}
      </ul>
      {change.isError && <p className="text-danger" role="alert">{(change.error as Error).message}</p>}
    </section>
  );
}

/** FR-7.2 / 7.3 / 7.4. */
export default function AIDashboard() {
  return (
    <div className="space-y-12">
      <Metrics />
      <Flags />
      <Feedback />
    </div>
  );
}
