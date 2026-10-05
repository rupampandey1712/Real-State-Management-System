import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../lib/auth";

/** Landing page for the emailed sign-in link. The token is in the URL fragment (#token=…), which browsers
 *  never send to servers, and it is removed from the address bar before the request is made. */
export default function LoginMagic() {
  const { verifyMagicLink } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // React strict mode runs effects twice; the link works only once
    started.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    window.history.replaceState(null, "", window.location.pathname);
    if (!token) {
      setError("This link is incomplete. Copy the whole link from the email, or request a new one.");
      return;
    }
    verifyMagicLink(token).then(() => navigate("/", { replace: true })).catch((e) => setError((e as Error).message));
  }, [verifyMagicLink, navigate]);

  return (
    <div className="mx-auto max-w-md space-y-4 pt-8" aria-live="polite">
      <h1 className="text-title font-extrabold tracking-tight">Signing you in</h1>
      {error ? (
        <>
          <p className="text-danger" role="alert">{error}</p>
          <Link to="/login" className="btn-primary">Send a new link</Link>
        </>
      ) : (
        <p className="text-slate">One moment…</p>
      )}
    </div>
  );
}
