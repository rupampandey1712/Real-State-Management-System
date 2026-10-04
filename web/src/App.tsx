import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { useAuth } from "./lib/auth";
import Account from "./pages/Account";
import Admin from "./pages/Admin";
import AgentListings from "./pages/AgentListings";
import Home from "./pages/Home";
import ListingDetail from "./pages/ListingDetail";
import ListingEditor from "./pages/ListingEditor";
import Login from "./pages/Login";
import LoginMagic from "./pages/LoginMagic";
import Privacy from "./pages/Privacy";
import Saved from "./pages/Saved";
import Search from "./pages/Search";

function RequireUser({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="text-slate">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="text-slate">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") return <p className="text-lg">This area is for administrators.</p>;
  return children;
}

function RequireAgent({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="text-slate">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "buyer") return <p className="text-lg">This area is for agents. <a href="/account" className="link">Apply to be an agent</a> from your account page.</p>;
  return children;
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/listings/:id" element={<ListingDetail />} />
        <Route path="/login" element={<Login />} />
        <Route path="/login/magic" element={<LoginMagic />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/me/saved" element={<RequireUser><Saved /></RequireUser>} />
        <Route path="/account" element={<RequireUser><Account /></RequireUser>} />
        <Route path="/admin" element={<RequireAdmin><Admin /></RequireAdmin>} />
        <Route path="/agent/listings" element={<RequireAgent><AgentListings /></RequireAgent>} />
        <Route path="/agent/listings/new" element={<RequireAgent><ListingEditor /></RequireAgent>} />
        <Route path="/agent/listings/:id/edit" element={<RequireAgent><ListingEditor /></RequireAgent>} />
        <Route path="*" element={<p className="text-lg">We couldn't find that page. <a href="/" className="link">Go to the home page</a></p>} />
      </Routes>
    </Layout>
  );
}
