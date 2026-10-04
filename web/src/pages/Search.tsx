import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import FilterChips, { filtersToParams, formatInr } from "../components/FilterChips";
import FilterPanel from "../components/FilterPanel";
import ListingCard from "../components/ListingCard";
import NLSearchBox from "../components/NLSearchBox";
import { track, type SearchMode } from "../lib/analytics";
import { api, newIdempotencyKey, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { SearchResponse } from "../lib/types";

// The map library is large; load it only when someone opens the map (keeps the list view fast, NFR-8).
const MapView = lazy(() => import("../components/MapView"));

/** URL params that shape the view rather than the filters: kept when filters change. */
const VIEW_PARAMS = ["sort", "view", "bbox"];
const SORTS: [string, string][] = [["relevance", "Best match"], ["newest", "Newest"], ["price_asc", "Price: low to high"], ["price_desc", "Price: high to low"]];

function ClassicSummary({ params, count }: { params: URLSearchParams; count: number }) {
  const price = (key: string) => formatInr(Number(params.get(key)));
  const parts = [
    params.get("bedrooms_min") && `${params.get("bedrooms_min")}${params.get("bedrooms_max") === params.get("bedrooms_min") ? "" : "+"} BHK`,
    params.get("property_type")?.replace(/_/g, " "),
    params.get("listing_type") && (params.get("listing_type") === "rent" ? "to rent" : "to buy"),
    params.get("locality") && `in ${params.get("locality")}`,
    params.get("city") && (params.get("locality") ? params.get("city") : `in ${params.get("city")}`),
    params.get("price_min") && params.get("price_max") ? `${price("price_min")}–${price("price_max")}`
      : params.get("price_max") ? `under ${price("price_max")}` : params.get("price_min") ? `over ${price("price_min")}` : null,
    params.get("furnishing")?.replace(/_/g, "-"),
    params.get("pet_policy") === "allowed" && "where pets are allowed",
    params.getAll("amenities").length > 0 && `with ${params.getAll("amenities").map((a) => a.replace(/_/g, " ")).join(" and ")}`,
    ...params.getAll("near").map((n) => `near ${n === "it_park" ? "an IT park" : `a ${n.replace("_", " ")}`}`),
  ].filter(Boolean);
  return (
    <p className="text-xl text-slate sm:text-2xl" aria-live="polite">
      <span className="font-semibold text-ink">{count}{count >= 20 ? "+" : ""} homes</span>
      {parts.length ? ` ${parts.join(" ")}` : ""}
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
      const filters = Object.fromEntries([...params.entries()].filter(([k]) => k !== "q" && k !== "cursor" && k !== "view"));
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
  const [params, setParams] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const q = params.get("q");
  const view = params.get("view") === "map" ? "map" : "list";
  const bbox = params.get("bbox");
  const sort = params.get("sort") ?? (q ? "relevance" : "newest");

  // The view toggle doesn't change the results, so it isn't part of the query key.
  const searchKey = useMemo(() => {
    const p = new URLSearchParams(params);
    p.delete("view");
    return p.toString();
  }, [params]);

  const query = useInfiniteQuery({
    queryKey: ["search", searchKey],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      if (q) return post<SearchResponse>("/search/nl", { query: q, cursor: pageParam, sort, bbox });
      const p = new URLSearchParams(searchKey);
      if (pageParam) p.set("cursor", pageParam);
      return api<SearchResponse>(`/search?${p.toString()}`);
    },
    getNextPageParam: (last) => last.next_cursor,
  });

  const first = query.data?.pages[0];
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const fallback = first?.meta.mode === "fallback";
  const mode: SearchMode = (first?.meta.mode as SearchMode | undefined) ?? (q ? "ai" : "classic");

  // Success metrics: one event per distinct search (not per "Show more" page or view toggle).
  useEffect(() => {
    if (first?.is_property_query) track({ type: "search_performed", mode });
  }, [searchKey, first?.is_property_query]); // only when the search or listing changes

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)));
    setParams(next);
  };

  /** Filter panel / chip edits: always a classic search, keeping sort, view and map area. */
  const applyFilters = (next: URLSearchParams) => {
    VIEW_PARAMS.forEach((k) => params.get(k) && next.set(k, params.get(k)!));
    setShowFilters(false);
    setParams(next);
  };

  const panelParams = q && first?.interpreted_filters ? filtersToParams(first.interpreted_filters) : params;
  const keepView = new URLSearchParams(VIEW_PARAMS.filter((k) => params.get(k) && k !== "sort").map((k) => [k, params.get(k)!]));

  return (
    <div className="space-y-8">
      <NLSearchBox initial={q ?? ""} />

      <div className="space-y-3 border-b border-rule pb-6">
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
          <FilterChips filters={first.interpreted_filters} count={items.length} keep={keepView} onEdit={() => setShowFilters(true)} />
        )}
        {first?.is_property_query && (!first.interpreted_filters || fallback) && (
          <ClassicSummary params={params} count={items.length} />
        )}
        {first && first.assumptions.length > 0 && (
          <p className="text-[0.95rem] text-slate">{first.assumptions.join(" ")}</p>
        )}

        {first?.is_property_query !== false && (
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button type="button" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters} aria-controls="filter-panel" className="btn-quiet">
              {showFilters ? "Hide filters" : "Filters"}
            </button>
            <label className="flex items-center gap-2 text-[0.95rem] text-slate">
              Sort
              <select value={sort} onChange={(e) => update({ sort: e.target.value })} className="field w-auto py-1.5">
                {SORTS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </label>
            <div className="inline-flex rounded-md border border-rule bg-paper p-0.5" role="group" aria-label="Show results as">
              {(["list", "map"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => update({ view: v === "map" ? "map" : null })}
                  className={`rounded px-3 py-1 text-[0.95rem] ${view === v ? "bg-ink font-semibold text-paper" : "text-slate hover:text-ink"}`}>
                  {v === "list" ? "List" : "Map"}
                </button>
              ))}
            </div>
            {bbox && (
              <button type="button" onClick={() => update({ bbox: null })} className="understood text-base" aria-label="Stop limiting results to the map area">
                In the map area <span aria-hidden>×</span>
              </button>
            )}
            {user && first?.is_property_query && <SaveSearchButton params={params} />}
          </div>
        )}
      </div>

      {showFilters && (
        <div id="filter-panel">
          <FilterPanel key={panelParams.toString()} params={panelParams} onApply={applyFilters} onClose={() => setShowFilters(false)} />
          {q && <p className="mt-2 text-sm text-slate">Changing filters runs a regular filter search, so it's instant and doesn't use the AI.</p>}
        </div>
      )}

      {first?.is_property_query && items.length === 0 && !query.isLoading && (
        <div className="max-w-lg space-y-2">
          <p className="text-lg font-semibold">No homes match all of that yet.</p>
          <p className="text-slate">{bbox ? "Zoom out or move the map, or remove the map area." : "Remove one of the underlined parts above, or widen the budget."}</p>
        </div>
      )}

      {view === "map" && first?.is_property_query && (
        <Suspense fallback={<div className="h-[28rem] animate-pulse rounded-lg bg-rule/50" aria-label="Loading map" />}>
          <MapView items={items} bbox={bbox} searchMode={mode} city={params.get("city") ?? first?.interpreted_filters?.city ?? null}
            onSearchArea={(box) => update({ bbox: box, cursor: null })} />
        </Suspense>
      )}

      <div className="grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => <ListingCard key={item.id} item={item} searchMode={mode} />)}
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
