import { Link } from "react-router-dom";

import type { SearchMode } from "../lib/analytics";
import type { SearchItem } from "../lib/types";
import FavouriteButton from "./FavouriteButton";

const CITY_TINT: Record<string, string> = {
  Pune: "bg-city-pune",
  Bengaluru: "bg-city-bengaluru",
  Mumbai: "bg-city-mumbai",
};

/** When there's no photo yet, show where the home is — the locality in large type on its city's tint. */
export function PhotoPlaceholder({ locality, city, bedrooms, large = false }: { locality: string; city: string; bedrooms: number; large?: boolean }) {
  return (
    <div className={`flex h-full flex-col justify-end p-5 ${CITY_TINT[city] ?? "bg-rule"}`} aria-hidden>
      <span className={`font-extrabold leading-none tracking-tight text-ink/80 ${large ? "text-5xl sm:text-6xl" : "text-3xl"}`}>{locality}</span>
      <span className="mt-1 text-slate">{bedrooms} BHK, {city}. Photos coming soon.</span>
    </div>
  );
}

/** `searchMode` is set on results pages so the listing page can count a search → view click-through. */
export default function ListingCard({ item, searchMode }: { item: SearchItem; searchMode?: SearchMode }) {
  return (
    <div className="relative">
    <Link to={`/listings/${item.id}`} state={searchMode ? { fromSearch: searchMode } : undefined} className="group block rounded-md">
      <div className="aspect-[4/3] overflow-hidden rounded-md">
        {item.thumbnail_url ? (
          <img src={item.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <PhotoPlaceholder locality={item.locality} city={item.city} bedrooms={item.bedrooms} />
        )}
      </div>
      <div className="mt-3">
        <p className="text-2xl font-bold tabular-nums text-ink">
          {item.price.display}
          {item.listing_type === "rent" && <span className="text-base font-medium text-slate"> a month</span>}
        </p>
        <p className="font-semibold text-ink group-hover:underline group-hover:decoration-2 group-hover:underline-offset-4">
          {item.bedrooms} BHK in {item.locality}
        </p>
        <p className="text-[0.95rem] text-slate">
          {item.carpet_area_sqft ? `${item.carpet_area_sqft.toLocaleString("en-IN")} sq ft, ` : ""}{item.city}
        </p>
        {item.match.reasons.length > 0 && (
          <p className="mt-1 text-sm font-medium text-leaf">{item.match.reasons.join(", ")}</p>
        )}
      </div>
    </Link>
    {/* Sibling of the link (a button can't live inside <a>); sits over the photo's top-right corner. */}
    <div className="absolute right-3 top-3">
      <FavouriteButton listingId={item.id} compact />
    </div>
    </div>
  );
}
