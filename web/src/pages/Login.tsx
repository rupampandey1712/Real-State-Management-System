import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import GoogleButton from "../components/GoogleButton";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { requestCode, verifyCode, signInWithGoogle } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sendCode = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await requestCode(email);
      setDevCode(result.dev_code ?? null);
      setStep("code");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await verifyCode(email, code);
      navigate("/");
    } catch {
      setError("That code didn't work. Check it, or send a new one.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-8 pt-8">
      <div className="space-y-2">
        <h1 className="text-title font-extrabold tracking-tight">Sign in</h1>
        <p className="text-slate">No password. We'll email you a sign-in link and a 6-digit code — use either.</p>
      </div>

      {step === "email" ? (
        <form onSubmit={sendCode} className="space-y-4">
          <label className="field-label">Email
            <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className="field mt-1 text-lg" />
          </label>
          <button disabled={busy} className="btn-primary w-full">{busy ? "Sending…" : "Email me a sign-in link"}</button>
          <p className="text-sm text-slate">Local test accounts: agent@example.com and admin@example.com.</p>
          <GoogleButton onCredential={(credential) => {
            setError(null);
            signInWithGoogle(credential).then(() => navigate("/")).catch((e) => setError((e as Error).message));
          }} />
          <p className="text-sm text-slate">By signing in you agree to how we handle your details, described in our <Link to="/privacy" className="link text-sm">privacy notice</Link>.</p>
        </form>
      ) : (
        <form onSubmit={verify} className="space-y-4">
          <p className="text-slate">Open the link in the email we sent to <span className="font-semibold text-ink">{email}</span>, or type the code here.</p>
          <label className="field-label">Code
            <input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} maxLength={6}
              className="field mt-1 text-center text-3xl font-bold tracking-[0.4em] tabular-nums" />
          </label>
          {devCode && (
            <p className="rounded-md bg-haldi-wash px-3 py-2 text-sm">
              Local development: your code is <strong className="tabular-nums">{devCode}</strong>. It's also in Mailpit at localhost:8025.
            </p>
          )}
          <button disabled={busy} className="btn-primary w-full">{busy ? "Signing in…" : "Sign in"}</button>
          <button type="button" onClick={() => { setStep("email"); setCode(""); }} className="link text-sm">Use a different email</button>
        </form>
      )}
      {error && <p className="text-danger" role="alert">{error}</p>}
    </div>
  );
}
