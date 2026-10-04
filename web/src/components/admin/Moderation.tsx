import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, post } from "../../lib/api";
import type { AdminListing, AuditEntry } from "../../lib/types";

const STATUS_LABEL: Record<string, string> = {
  published: "Live", removed: "Taken down", suspended: "Agent suspended", draft: "Draft", unpublished: "Hidden", archived: "Archived",
};

function ListingRow({ listing }: { listing: AdminListing }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: ["admin-listing-history", listing.id],
    queryFn: () => api<AuditEntry[]>(`/admin/listings/${listing.id}/moderation`),
    enabled: showHistory,
  });
  const action = listing.status === "published" ? "takedown" : listing.status === "removed" ? "restore" : null;
  const act = useMutation({
    mutationFn: () => action === "takedown"
      ? post<AdminListing>(`/admin/listings/${listing.id}/takedown`, { reason })
      : post<AdminListing>(`/admin/listings/${listing.id}/restore`, { reason }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["admin-listings"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-listing-history", listing.id] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    act.mutate();
  };

  return (
    <li className="space-y-2 border-t border-rule py-3 last:border-b">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Link to={`/listings/${listing.id}`} className="min-w-0 flex-1 truncate font-semibold hover:underline">{listing.title}</Link>
        <span className="text-sm text-slate">{listing.locality}, {listing.city} · {listing.price.display}</span>
        <span className={`w-32 text-sm font-semibold ${listing.status === "published" ? "text-leaf" : "text-slate"}`}>{STATUS_LABEL[listing.status] ?? listing.status}</span>
        <button onClick={() => setShowHistory((s) => !s)} aria-expanded={showHistory} className="text-sm font-medium text-slate hover:text-ink">History</button>
        {action && !open && (
          <button onClick={() => setOpen(true)} className={`btn-quiet py-1 ${action === "takedown" ? "text-danger" : ""}`}>
            {action === "takedown" ? "Take down" : "Restore"}
          </button>
        )}
      </div>
      {listing.last_action && (
        <p className="text-sm text-slate">
          Last action: {listing.last_action.action} on {new Date(listing.last_action.created_at).toLocaleDateString("en-IN", { dateStyle: "medium" })} — “{listing.last_action.reason}”
        </p>
      )}
      {showHistory && (
        <ul className="space-y-1 text-sm">
          {history.data?.length === 0 && <li className="text-slate">No moderation actions.</li>}
          {history.data?.map((a) => (
            <li key={a.id}><span className="font-semibold">{a.action}</span> <span className="text-slate">{new Date(a.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span> — “{a.reason}”</li>
          ))}
        </ul>
      )}
      {open && action && (
        <form onSubmit={submit} className="flex flex-wrap gap-2">
          <label className="sr-only" htmlFor={`reason-${listing.id}`}>Reason</label>
          <input id={`reason-${listing.id}`} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} maxLength={1000}
            placeholder={action === "takedown" ? "Why is it coming down? (logged)" : "Why is it being restored? (logged)"} className="field max-w-lg flex-1 py-1" />
          <button disabled={reason.trim().length < 5 || act.isPending} className="btn-primary py-1">{action === "takedown" ? "Take down" : "Restore"}</button>
          <button type="button" onClick={() => setOpen(false)} className="btn-quiet py-1">Cancel</button>
          {act.isError && <p className="w-full text-sm text-danger" role="alert">{(act.error as Error).message}</p>}
        </form>
      )}
    </li>
  );
}

/** FR-7.1: take listings down and restore them, with the reason logged. */
export default function Moderation() {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("published");
  const listings = useQuery({
    queryKey: ["admin-listings", query, status],
    queryFn: () => api<AdminListing[]>(`/admin/listings?${new URLSearchParams({ ...(query && { q: query }), ...(status && { status }) })}`),
  });
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-bold">Listings</h2>
      <form onSubmit={(e) => { e.preventDefault(); setQuery(term.trim()); }} className="flex flex-wrap gap-3" role="search">
        <label htmlFor="listing-search" className="sr-only">Find by title, locality or id</label>
        <input id="listing-search" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Title, locality or listing id" className="field max-w-sm" />
        <label className="flex items-center gap-2 text-[0.95rem] text-slate">Status
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="field w-auto py-2">
            <option value="">Any</option>
            {Object.entries(STATUS_LABEL).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </label>
        <button className="btn-primary">Find</button>
      </form>
      {listings.isLoading && <p className="text-slate">Loading…</p>}
      {listings.data?.length === 0 && <p className="text-slate">No listings match.</p>}
      <ul>{listings.data?.map((l) => <ListingRow key={`${l.id}-${l.status}`} listing={l} />)}</ul>
    </section>
  );
}
