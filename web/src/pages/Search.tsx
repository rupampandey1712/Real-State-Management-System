import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import FilterChips from "../components/FilterChips";
import ListingCard from "../components/ListingCard";
import NLSearchBox from "../components/NLSearchBox";
import { api, newIdempotencyKey, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { SearchResponse } from "../lib/types";

function ClassicSummary({ params, count }: { params: URLSearchParams; count: number }) {
  const parts = [
    params.get("bedrooms_min") && `${params.get("bedrooms_min")}+ BHK`,
    params.get("listing_type") && (params.get("listing_type") === "rent" ? "to rent" : "to buy"),
    params.get("locality") && `in ${params.get("locality")}`,
    params.get("city") && (params.get("locality") ? params.get("city") : `in ${params.get("city")}`),
    params.get("price_max") && `under ₹${Number(params.get("price_max")).toLocaleString("en-IN")}`,
  ].filter(Boolean);
  return (
    <p className="text-xl text-slate sm:text-2xl">
      <span className="font-semibold text-ink">{count}{count >= 20 ? "+" : ""} homes</span>
      {parts.length ? ` ${parts.join(" ")}` : ", newest first"}
    </p>
  );
}

function SaveSearchButton({ params }: { params: URLSearchParams }) {
  const queryClient = useQueryClient();
  const q = params.get("q");
  const signature = params.toString();
  // One key per search: saving the same results twice creates one saved search.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), [signature]);
  const save = useMutation({
    mutationFn: () => {
      const filters = Object.fromEntries([...params.entries()].filter(([k]) => k !== "q" && k !== "cursor"));
      const name = q ?? (Object.values(filters).join(", ") || "All homes");
      return post("/me/saved-searches", { name: name.slice(0, 80), raw_query: q, filters }, { idempotencyKey });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
  if (save.isSuccess) {
    return <p className="text-leaf" role="status">Search saved. <Link to="/me/saved" className="link">See saved searches</Link></p>;
  }
  return (
    <button onClick={() => save.mutate()} disabled={save.isPending} className="btn-quiet">
      {save.isPending ? "Saving…" : "Save this search"}
    </button>
  );
}

export default function Search() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const q = params.get("q");

  const query = useInfiniteQuery({
    queryKey: ["search", params.toString()],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      if (q) return post<SearchResponse>("/search/nl", { query: q, cursor: pageParam });
      const p = new URLSearchParams(params);
      if (pageParam) p.set("cursor", pageParam);
      return api<SearchResponse>(`/search?${p.toString()}`);
    },
    getNextPageParam: (last) => last.next_cursor,
  });

  const first = query.data?.pages[0];
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const fallback = first?.meta.mode === "fallback";

  return (
    <div className="space-y-8">
      <NLSearchBox initial={q ?? ""} />

      <div className="space-y-2 border-b border-rule pb-6">
        {query.isLoading && <p className="text-xl text-slate">Reading your search…</p>}
        {query.isError && (
          <p className="text-danger">We couldn't load results. Check your connection and search again.</p>
        )}
        {first && !first.is_property_query && (
          <p className="text-xl text-slate">
            That doesn't look like a home search. Try something like{" "}
            <Link to="/search?q=2%20BHK%20in%20Pune%20under%2080%20lakh" className="link">2 BHK in Pune under 80 lakh</Link>.
          </p>
        )}
        {first?.is_property_query && first.interpreted_filters && !fallback && (
          <FilterChips filters={first.interpreted_filters} count={items.length} />
        )}
        {first?.is_property_query && (!first.interpreted_filters || fallback) && (
          <ClassicSummary params={params} count={items.length} />
        )}
        {first && first.assumptions.length > 0 && (
          <p className="text-[0.95rem] text-slate">{first.assumptions.join(" ")}</p>
        )}
        {user && first?.is_property_query && <div className="pt-2"><SaveSearchButton params={params} /></div>}
      </div>

      {first?.is_property_query && items.length === 0 && (
        <div className="max-w-lg space-y-2">
          <p className="text-lg font-semibold">No homes match all of that yet.</p>
          <p className="text-slate">Remove one of the underlined parts above, or widen the budget.</p>
        </div>
      )}

      <div className="grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => <ListingCard key={item.id} item={item} />)}
      </div>

      {query.hasNextPage && (
        <div className="flex justify-center">
          <button onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage} className="btn-quiet">
            {query.isFetchingNextPage ? "Loading more homes…" : "Show more homes"}
          </button>
        </div>
      )}
    </div>
  );
}
