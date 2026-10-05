import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { del, post } from "../lib/api";
import { useAuth } from "../lib/auth";

const ROLE_LABEL = { buyer: "Home seeker", agent: "Agent", admin: "Administrator" } as const;

/** T1.16: a buyer asks to list homes; an admin verifies the details before they can publish. */
function AgentApplication() {
  const { reloadUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post("/me/agent-request", {
        name: form.get("name"), phone: form.get("phone"),
        agency_name: form.get("agency_name") || null, rera_agent_id: form.get("rera_agent_id") || null,
      });
      await reloadUser();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <section className="space-y-2 border-t border-rule pt-6">
        <h2 className="text-xl font-bold">List homes on EstateAI</h2>
        <p className="text-slate">Agents can list homes once we've checked their details, usually within two working days.</p>
        <button onClick={() => setOpen(true)} className="btn-quiet">Apply to be an agent</button>
      </section>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-3 border-t border-rule pt-6">
      <h2 className="text-xl font-bold">Apply to be an agent</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="field-label">Full name<input name="name" required minLength={2} maxLength={120} autoComplete="name" className="field mt-1" /></label>
        <label className="field-label">Phone<input name="phone" required pattern="\+?[0-9 \-]{8,16}" autoComplete="tel" className="field mt-1" /></label>
        <label className="field-label">Agency (optional)<input name="agency_name" maxLength={120} className="field mt-1" /></label>
        <label className="field-label">RERA agent registration (optional)<input name="rera_agent_id" maxLength={40} className="field mt-1" /></label>
      </div>
      <p className="text-sm text-slate">An administrator uses these to verify you. They aren't shown to buyers or sent to AI features.</p>
      <div className="flex gap-3">
        <button disabled={busy} className="btn-primary">{busy ? "Sending…" : "Send application"}</button>
        <button type="button" onClick={() => setOpen(false)} className="btn-quiet">Cancel</button>
      </div>
      {error && <p className="text-danger" role="alert">{error}</p>}
    </form>
  );
}

function DeleteAccount() {
  const { forget } = useAuth();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const remove = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await del("/me", { confirm: "DELETE" });
      forget();
      navigate("/", { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={remove} className="space-y-3 border-t border-rule pt-6">
      <h2 className="text-xl font-bold text-danger">Delete your account</h2>
      <p className="text-slate">
        Your email, saved homes, saved searches and the contact details in enquiries you sent are erased.
        If you're an agent, your listings are archived. This can't be undone.
      </p>
      <label className="field-label">Type DELETE to confirm
        <input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="field mt-1 max-w-xs" autoComplete="off" />
      </label>
      <button disabled={confirm !== "DELETE" || busy} className="btn-primary bg-danger hover:bg-danger/90">
        {busy ? "Deleting…" : "Delete my account"}
      </button>
      {error && <p className="text-danger" role="alert">{error}</p>}
    </form>
  );
}

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

      <p className="flex flex-wrap gap-x-6"><Link to="/me/saved" className="link">Saved homes and searches</Link><Link to="/privacy" className="link">How we use your details</Link></p>

      {user.role === "buyer" && <AgentApplication />}

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

      {user.role !== "admin" && <DeleteAccount />}
    </div>
  );
}
