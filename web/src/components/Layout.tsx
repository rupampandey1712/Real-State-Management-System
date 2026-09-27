import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

import { useAuth } from "../lib/auth";

export default function Layout({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `text-[0.95rem] font-medium ${isActive ? "text-ink underline decoration-2 decoration-ink underline-offset-8" : "text-slate hover:text-ink"}`;

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 btn-primary">
        Skip to content
      </a>
      <header className="border-b border-rule">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-5">
          <Link to="/" className="text-2xl font-extrabold tracking-tight text-ink">EstateAI</Link>
          <nav className="flex gap-5 overflow-x-auto whitespace-nowrap" aria-label="Main">
            <NavLink to="/search" className={navClass}>Find a home</NavLink>
            {user && <NavLink to="/me/saved" className={navClass}>Saved</NavLink>}
            {user && user.role !== "buyer" && <NavLink to="/agent/listings" className={navClass}>My listings</NavLink>}
            {user?.role === "admin" && <NavLink to="/admin" className={navClass}>People</NavLink>}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-[0.95rem]">
            {user ? (
              <>
                <Link to="/account" className="text-slate hover:text-ink"><span className="sm:hidden">Account</span><span className="hidden sm:inline">{user.email}</span></Link>
                <button onClick={() => void signOut()} className="font-medium text-slate hover:text-ink">Sign out</button>
              </>
            ) : (
              <Link to="/login" className="btn-quiet py-1.5">Sign in</Link>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-5 py-8">{children}</main>
      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-5 py-6 text-sm text-slate">
          <p>Homes in Pune, Bengaluru and Mumbai.</p>
          <p>AI answers use only what a listing says. Confirm details with the agent before you decide.</p>
        </div>
      </footer>
    </div>
  );
}
