import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { ListingSummary } from "../lib/types";

interface Enquiry {
  id: string;
  listingId: string;
  listingTitle: string;
  name: string;
  email: string;
  phone: string | null;
  message: string;
  createdAt: string;
}

const STATUS: Record<string, { label: string; className: string }> = {
  published: { label: "Live", className: "text-leaf" },
  draft: { label: "Draft", className: "text-slate" },
  unpublished: { label: "Hidden", className: "text-danger" },
  removed: { label: "Taken down", className: "text-danger" },
  suspended: { label: "Suspended", className: "text-danger" },
};

export default function AgentListings() {
  const listings = useQuery({ queryKey: ["agent-listings"], queryFn: () => api<ListingSummary[]>("/agent/listings") });
  const enquiries = useQuery({ queryKey: ["agent-enquiries"], queryFn: () => api<Enquiry[]>("/agent/enquiries") });

  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_22rem]">
      <section className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h1 className="text-title font-extrabold tracking-tight">My listings</h1>
          <Link to="/agent/listings/new" className="btn-primary">Add a listing</Link>
        </div>
        {listings.isLoading && <p className="text-slate">Loading your listings…</p>}
        {listings.data?.length === 0 && (
          <p className="text-slate">You haven't added a listing yet. Add one and the AI can draft its description for you.</p>
        )}
        <ul>
          {listings.data?.map((l) => {
            const status = STATUS[l.status] ?? { label: l.status, className: "text-slate" };
            return (
              <li key={l.id} className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-rule py-4 last:border-b">
                <div className="min-w-0 flex-1">
                  <Link to={`/agent/listings/${l.id}/edit`} className="block truncate text-lg font-semibold hover:underline">{l.title}</Link>
                  <p className="text-slate">
                    {l.locality}, {l.city}{l.documents_count ? `, ${l.documents_count} document${l.documents_count > 1 ? "s" : ""}` : ""}
                    {l.description_ai && <span className="ml-2 rounded bg-haldi-wash px-1.5 text-xs font-semibold text-ink">AI-assisted</span>}
                  </p>
                </div>
                <p className="w-24 text-lg font-bold tabular-nums">{l.price.display}</p>
                <p className={`w-24 font-semibold ${status.className}`}>{status.label}</p>
                <Link to={`/listings/${l.id}`} className="link text-sm">View</Link>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="space-y-4">
        <h2 className="text-2xl font-bold">Messages from buyers</h2>
        {enquiries.data?.length === 0 && <p className="text-slate">No messages yet. They'll appear here and in your email.</p>}
        <ul className="space-y-3">
          {enquiries.data?.map((e) => (
            <li key={e.id} className="rounded-lg border border-rule bg-paper p-4">
              <p className="font-semibold">{e.name}</p>
              <p className="text-sm text-slate">About {e.listingTitle}</p>
              <p className="mt-2">{e.message}</p>
              <p className="mt-2 text-sm text-slate">
                <a href={`mailto:${e.email}`} className="link text-sm">{e.email}</a>
                {e.phone ? `, ${e.phone}` : ""}
                <span className="block">{new Date(e.createdAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
