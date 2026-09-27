import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../lib/auth";

const ROLE_LABEL = { buyer: "Home seeker", agent: "Agent", admin: "Administrator" } as const;

export default function Account() {
  const { user, signOut, signOutEverywhere } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  if (!user) return null;

  return (
    <div className="max-w-xl space-y-8">
      <h1 className="text-title font-extrabold tracking-tight">Your account</h1>
      <dl className="grid grid-cols-2 gap-x-6">
        <div className="border-t border-rule py-3">
          <dt className="text-sm text-slate">Email</dt>
          <dd className="text-lg font-semibold break-all">{user.email}</dd>
        </div>
        <div className="border-t border-rule py-3">
          <dt className="text-sm text-slate">Account type</dt>
          <dd className="text-lg font-semibold">
            {ROLE_LABEL[user.role]}
            {user.role === "agent" && !user.agent_verified && <span className="block text-sm font-normal text-slate">Awaiting verification</span>}
          </dd>
        </div>
      </dl>

      <p><Link to="/me/saved" className="link">Saved homes and searches</Link></p>

      <section className="space-y-3 border-t border-rule pt-6">
        <h2 className="text-xl font-bold">Sessions</h2>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => void signOut().then(() => navigate("/"))} className="btn-quiet">Sign out</button>
          {confirming ? (
            <>
              <button onClick={() => void signOutEverywhere().then(() => navigate("/login"))} className="btn-primary bg-danger hover:bg-danger/90">
                Yes, sign out of all devices
              </button>
              <button onClick={() => setConfirming(false)} className="btn-quiet">Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirming(true)} className="btn-quiet text-danger">Sign out of all devices</button>
          )}
        </div>
        <p className="text-sm text-slate">Use this if you signed in on a shared or lost device. Every session ends right away, including this one.</p>
      </section>
    </div>
  );
}
