import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "../lib/api";

interface Providers {
  google_client_id: string | null;
}

interface GoogleId {
  accounts: {
    id: {
      initialize: (options: { client_id: string; callback: (response: { credential: string }) => void }) => void;
      renderButton: (element: HTMLElement, options: Record<string, string | number>) => void;
    };
  };
}

const GIS_SRC = "https://accounts.google.com/gsi/client";

function loadGoogleScript(): Promise<GoogleId> {
  const existing = (window as unknown as { google?: GoogleId }).google;
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement("script"), { src: GIS_SRC, async: true });
    script.onload = () => resolve((window as unknown as { google: GoogleId }).google);
    script.onerror = () => reject(new Error("Google sign-in couldn't load."));
    document.head.appendChild(script);
  });
}

/** "Sign in with Google" (FR-6.1, ADR-0017). Rendered only when the identity service has a client id;
 *  Google's script is loaded only then, so nobody else's browser talks to Google. */
export default function GoogleButton({ onCredential }: { onCredential: (credential: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  const { data } = useQuery({ queryKey: ["auth-providers"], queryFn: () => api<Providers>("/auth/providers"), staleTime: Infinity });
  const clientId = data?.google_client_id;

  useEffect(() => {
    if (!clientId || !ref.current) return;
    let cancelled = false;
    loadGoogleScript().then((google) => {
      if (cancelled || !ref.current) return;
      google.accounts.id.initialize({ client_id: clientId, callback: (r) => callback.current(r.credential) });
      google.accounts.id.renderButton(ref.current, { theme: "outline", size: "large", text: "continue_with", width: 320 });
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [clientId]);

  if (!clientId) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm text-slate"><span className="h-px flex-1 bg-rule" />or<span className="h-px flex-1 bg-rule" /></div>
      <div ref={ref} className="flex justify-center" />
    </div>
  );
}
