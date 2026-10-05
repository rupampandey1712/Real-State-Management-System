import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Moderation from "../components/admin/Moderation";
import { api, post } from "../lib/api";
import type { AdminUser, AuditEntry, User } from "../lib/types";

const AIDashboard = lazy(() => import("../components/admin/AIDashboard"));
const SuccessMetrics = lazy(() => import("../components/admin/SuccessMetrics"));

type Role = User["role"];
const TABS = [["people", "People"], ["listings", "Listings"], ["ai", "AI"], ["metrics", "Success metrics"]] as const;

function History({ userId }: { userId: string }) {
  const { data } = useQuery({ queryKey: ["admin-user-actions", userId], queryFn: () => api<AuditEntry[]>(`/admin/users/${userId}/actions`) });
  if (!data) return <p className="text-sm text-slate">Loading…</p>;
  if (data.length === 0) return <p className="text-sm text-slate">No admin actions yet.</p>;
  return (
    <ul className="space-y-1 text-sm">
      {data.map((a) => (
        <li key={a.id}>
          <span className="font-semibold">{a.action}{a.detail ? ` → ${a.detail}` : ""}</span>{" "}
          <span className="text-slate">{new Date(a.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span> — “{a.reason}”
        </li>
      ))}
    </ul>
  );
}

function UserRow({ user }: { user: AdminUser }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<Role>(user.role);
  const [verified, setVerified] = useState(user.agent_verified);
  const [reason, setReason] = useState("");
  const [panel, setPanel] = useState<"none" | "suspend" | "history">("none");
  const dirty = role !== user.role || verified !== user.agent_verified;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    void queryClient.invalidateQueries({ queryKey: ["admin-user-actions", user.id] });
  };
  const save = useMutation({
    mutationFn: () => post<AdminUser>(`/admin/users/${user.id}/role`, { role, agent_verified: verified, reason: reason.trim() || "Role updated by an administrator." }),
    onSuccess: () => { setReason(""); refresh(); },
  });
  const suspension = useMutation({
    mutationFn: () => user.suspended_at
      ? post<AdminUser>(`/admin/users/${user.id}/reinstate`, { reason })
      : post<AdminUser>(`/admin/users/${user.id}/suspend`, { reason }),
    onSuccess: () => { setReason(""); setPanel("none"); refresh(); },
  });
  const error = (save.error ?? suspension.error) as Error | null;

  return (
    <li className="space-y-2 border-t border-rule py-3 last:border-b">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="min-w-0 flex-1 break-all font-medium">
          {user.email}
          {user.suspended_at && <span className="ml-2 rounded bg-danger px-1.5 text-xs font-semibold text-paper">Suspended</span>}
        </span>
        <label className="text-sm text-slate">
          <span className="sr-only">Role for {user.email}</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="field w-36 py-1">
            <option value="buyer">Home seeker</option>
            <option value="agent">Agent</option>
            <option value="admin">Administrator</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={verified} disabled={role !== "agent"} onChange={(e) => setVerified(e.target.checked)} className="size-4 accent-ink" />
          Verified agent
        </label>
        <button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className="btn-quiet py-1">{save.isPending ? "Saving…" : "Save"}</button>
        <button onClick={() => setPanel(panel === "suspend" ? "none" : "suspend")} className={`text-sm font-medium ${user.suspended_at ? "text-ink" : "text-danger"} hover:underline`}>
          {user.suspended_at ? "Reinstate" : "Suspend"}
        </button>
        <button onClick={() => setPanel(panel === "history" ? "none" : "history")} className="text-sm font-medium text-slate hover:text-ink">History</button>
      </div>
      {user.role === "agent" && (user.agency_name || user.rera_agent_id || user.phone) && (
        <p className="text-sm text-slate">
          Application: {[user.name, user.phone, user.agency_name, user.rera_agent_id && `RERA ${user.rera_agent_id}`].filter(Boolean).join(" · ")}
          {user.agent_requested_at && ` · applied ${new Date(user.agent_requested_at).toLocaleDateString("en-IN", { dateStyle: "medium" })}`}
        </p>
      )}
      {dirty && (
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Reason for the change (logged)"
          aria-label={`Reason for changing ${user.email}`} className="field max-w-lg py-1 text-sm" />
      )}
      {panel === "suspend" && (
        <form onSubmit={(e) => { e.preventDefault(); suspension.mutate(); }} className="flex flex-wrap gap-2">
          <input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} maxLength={1000}
            aria-label={`Reason to ${user.suspended_at ? "reinstate" : "suspend"} ${user.email}`}
            placeholder={user.suspended_at ? "Why reinstate? (logged)" : "Why suspend? (logged). Their live listings are hidden."} className="field max-w-lg flex-1 py-1 text-sm" />
          <button disabled={reason.trim().length < 5 || suspension.isPending} className={`btn-primary py-1 ${user.suspended_at ? "" : "bg-danger hover:bg-danger/90"}`}>
            {user.suspended_at ? "Reinstate" : "Suspend"}
          </button>
        </form>
      )}
      {panel === "history" && <History userId={user.id} />}
      {save.isSuccess && !dirty && <span className="text-sm text-leaf" role="status">Saved. Their current sessions were ended.</span>}
      {error && <span className="text-sm text-danger" role="alert">{error.message}</span>}
    </li>
  );
}

function KeyRotation() {
  const [confirming, setConfirming] = useState(false);
  const rotate = useMutation({ mutationFn: () => post<{ kid: string }>("/admin/keys/rotate") });
  return (
    <section className="space-y-3 border-t border-rule pt-6">
      <h2 className="text-xl font-bold">Sign-in keys</h2>
      <p className="max-w-prose text-slate">
        Keys rotate automatically every 30 days. Rotate now if a key may have leaked. People stay signed in:
        the old key keeps working until the tokens it signed expire (about 20 minutes).
      </p>
      {rotate.isSuccess ? (
        <p className="text-leaf" role="status">New key is live (<span className="font-mono text-sm">{rotate.data.kid.slice(0, 8)}…</span>).</p>
      ) : confirming ? (
        <div className="flex gap-3">
          <button onClick={() => rotate.mutate()} disabled={rotate.isPending} className="btn-primary">
            {rotate.isPending ? "Rotating…" : "Yes, rotate keys now"}
          </button>
          <button onClick={() => setConfirming(false)} className="btn-quiet">Cancel</button>
        </div>
      ) : (
        <button onClick={() => setConfirming(true)} className="btn-quiet">Rotate keys</button>
      )}
      {rotate.isError && <p className="text-danger" role="alert">{(rotate.error as Error).message}</p>}
    </section>
  );
}

function People() {
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"" | "pending" | "suspended">("");
  const users = useQuery({
    queryKey: ["admin-users", query, filter],
    queryFn: () => api<AdminUser[]>(`/admin/users?${new URLSearchParams({ ...(query && { email: query }), ...(filter && { [filter]: "true" }) })}`),
  });
  return (
    <div className="space-y-10">
      <section className="space-y-5">
        <form onSubmit={(e) => { e.preventDefault(); setQuery(email.trim()); }} className="flex max-w-2xl flex-wrap gap-3" role="search">
          <label htmlFor="user-search" className="sr-only">Find by email</label>
          <input id="user-search" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Find by email" className="field max-w-sm" />
          <label className="flex items-center gap-2 text-[0.95rem] text-slate">Show
            <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="field w-auto py-2">
              <option value="">Everyone</option>
              <option value="pending">Agents awaiting verification</option>
              <option value="suspended">Suspended</option>
            </select>
          </label>
          <button className="btn-primary">Find</button>
        </form>
        <p className="text-sm text-slate">Verify an agent after checking their documents. Changing a role or suspending someone signs them out everywhere at once. Every change is logged with its reason.</p>
        {users.isLoading && <p className="text-slate">Loading…</p>}
        {users.data?.length === 0 && <p className="text-slate">No one matches.</p>}
        <ul>{users.data?.map((u) => <UserRow key={`${u.id}-${u.role}-${u.agent_verified}-${u.suspended_at}`} user={u} />)}</ul>
      </section>
      <KeyRotation />
    </div>
  );
}

export default function Admin() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "people";
  return (
    <div className="space-y-8">
      <h1 className="text-title font-extrabold tracking-tight">Admin</h1>
      <div className="flex gap-1 border-b border-rule" role="tablist" aria-label="Admin sections">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setParams(id === "people" ? {} : { tab: id })}
            className={`-mb-px border-b-2 px-4 py-2 font-semibold ${tab === id ? "border-ink text-ink" : "border-transparent text-slate hover:text-ink"}`}>
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "people" && <People />}
        {tab === "listings" && <Moderation />}
        {tab === "ai" && <Suspense fallback={<p className="text-slate">Loading…</p>}><AIDashboard /></Suspense>}
        {tab === "metrics" && <Suspense fallback={<p className="text-slate">Loading…</p>}><SuccessMetrics /></Suspense>}
      </div>
    </div>
  );
}
