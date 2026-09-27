import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, post } from "../lib/api";
import type { User } from "../lib/types";

type Role = User["role"];

function UserRow({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<Role>(user.role);
  const [verified, setVerified] = useState(user.agent_verified);
  const dirty = role !== user.role || verified !== user.agent_verified;
  const save = useMutation({
    mutationFn: () => post<User>(`/admin/users/${user.id}/role`, { role, agent_verified: verified }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  return (
    <li className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-rule py-3 last:border-b">
      <span className="min-w-0 flex-1 break-all font-medium">{user.email}</span>
      <label className="text-sm text-slate">
        <span className="sr-only">Role for {user.email}</span>
        <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="field w-36 py-1">
          <option value="buyer">Home seeker</option>
          <option value="agent">Agent</option>
          <option value="admin">Administrator</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} className="size-4 accent-ink" />
        Verified agent
      </label>
      <button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className="btn-quiet py-1">
        {save.isPending ? "Saving…" : "Save"}
      </button>
      {save.isSuccess && !dirty && <span className="text-sm text-leaf" role="status">Saved. Their current sessions were ended.</span>}
      {save.isError && <span className="text-sm text-danger" role="alert">{(save.error as Error).message}</span>}
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

export default function Admin() {
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState("");
  const users = useQuery({
    queryKey: ["admin-users", query],
    queryFn: () => api<User[]>(`/admin/users${query ? `?email=${encodeURIComponent(query)}` : ""}`),
  });

  return (
    <div className="space-y-10">
      <section className="space-y-5">
        <h1 className="text-title font-extrabold tracking-tight">People</h1>
        <form onSubmit={(e) => { e.preventDefault(); setQuery(email.trim()); }} className="flex max-w-lg gap-3" role="search">
          <label htmlFor="user-search" className="sr-only">Find by email</label>
          <input id="user-search" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Find by email" className="field" />
          <button className="btn-primary">Find</button>
        </form>
        <p className="text-sm text-slate">Verify an agent here after checking their documents. Changing a role signs that person out everywhere so it takes effect at once.</p>
        {users.isLoading && <p className="text-slate">Loading…</p>}
        {users.data?.length === 0 && <p className="text-slate">No one matches “{query}”.</p>}
        <ul>{users.data?.map((u) => <UserRow key={`${u.id}-${u.role}-${u.agent_verified}`} user={u} />)}</ul>
      </section>
      <KeyRotation />
    </div>
  );
}
