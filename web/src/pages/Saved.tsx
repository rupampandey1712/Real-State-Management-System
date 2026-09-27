import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useFavourites } from "../components/FavouriteButton";
import ListingCard from "../components/ListingCard";
import { api } from "../lib/api";
import type { Listing, SavedSearch, SearchItem } from "../lib/types";

function toItem(l: Listing): SearchItem {
  return {
    id: l.id, title: l.title, listing_type: l.listing_type, property_type: l.property_type, price: l.price,
    bedrooms: l.bedrooms, bathrooms: l.bathrooms, carpet_area_sqft: l.carpet_area_sqft, locality: l.locality,
    city: l.city, thumbnail_url: l.images[0]?.thumb_url ?? null, match: { score: 0, reasons: [] },
  };
}

/** A saved search re-runs the same way it was made: as an AI sentence, or as plain filters. */
export function savedSearchHref(s: SavedSearch): string {
  if (s.raw_query) return `/search?q=${encodeURIComponent(s.raw_query)}`;
  return `/search?${new URLSearchParams(s.filters).toString()}`;
}

export default function Saved() {
  const queryClient = useQueryClient();
  const favourites = useFavourites();
  const listings = useQueries({
    queries: (favourites.data ?? []).map((f) => ({
      queryKey: ["listing", f.listingId],
      queryFn: () => api<Listing>(`/listings/${f.listingId}`),
      retry: false, // a listing that was taken down returns 404
    })),
  });
  const searches = useQuery({ queryKey: ["saved-searches"], queryFn: () => api<SavedSearch[]>("/me/saved-searches") });
  const removeSearch = useMutation({
    mutationFn: (id: string) => api(`/me/saved-searches/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });

  const available = listings.filter((q) => q.data).map((q) => q.data as Listing);
  const unavailable = listings.filter((q) => q.isError).length;

  return (
    <div className="space-y-12">
      <section className="space-y-5">
        <h1 className="text-title font-extrabold tracking-tight">Saved homes</h1>
        {favourites.isLoading && <p className="text-slate">Loading your saved homes…</p>}
        {favourites.data?.length === 0 && (
          <p className="text-slate">
            Nothing saved yet. Use <span className="font-semibold text-ink">Save</span> on any home to keep it here.{" "}
            <Link to="/search" className="link">Find homes</Link>
          </p>
        )}
        <div className="grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
          {available.map((l) => <ListingCard key={l.id} item={toItem(l)} />)}
        </div>
        {unavailable > 0 && (
          <p className="text-sm text-slate">
            {unavailable === 1 ? "1 saved home is" : `${unavailable} saved homes are`} no longer listed.
          </p>
        )}
      </section>

      <section className="space-y-4 border-t border-rule pt-8">
        <h2 className="text-2xl font-bold">Saved searches</h2>
        {searches.data?.length === 0 && (
          <p className="text-slate">No saved searches. On any results page, use <span className="font-semibold text-ink">Save this search</span>.</p>
        )}
        <ul>
          {searches.data?.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-rule py-3 last:border-b">
              <Link to={savedSearchHref(s)} className="min-w-0 flex-1 truncate text-lg font-semibold hover:underline">{s.name}</Link>
              <span className="text-sm text-slate">{new Date(s.createdAt).toLocaleDateString("en-IN", { dateStyle: "medium" })}</span>
              <button onClick={() => removeSearch.mutate(s.id)} className="text-sm font-medium text-slate hover:text-danger">Remove</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
