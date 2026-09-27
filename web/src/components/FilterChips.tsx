import { useNavigate } from "react-router-dom";

import type { InterpretedFilters } from "../lib/types";

export function formatInr(rupees: number): string {
  if (rupees >= 10_000_000) return `₹${+(rupees / 10_000_000).toFixed(2)} Cr`;
  if (rupees >= 100_000) return `₹${+(rupees / 100_000).toFixed(2)} L`;
  return `₹${rupees.toLocaleString("en-IN")}`;
}

interface Token {
  key: string;
  text: string;
  /** Plain text before the token, e.g. the comma in "in Kharadi, Pune". */
  prefix?: string;
  /** Classic-search param this token maps to; tokens without one (near, feel) are dropped on edit. */
  param?: [string, string];
}

const PROPERTY_NOUNS: Record<string, string> = {
  apartment: "apartments",
  independent_house: "independent houses",
  villa: "villas",
  plot: "plots",
  commercial: "commercial spaces",
};

/** Builds the sentence "2 BHK apartments to buy in Kharadi, Pune under ₹80 L, near metro". */
function sentence(f: InterpretedFilters): { before: Token[]; noun: Token; after: Token[] } {
  const before: Token[] = [];
  const after: Token[] = [];
  if (f.bedrooms_min !== null) {
    const text = f.bedrooms_max !== null && f.bedrooms_max !== f.bedrooms_min ? `${f.bedrooms_min}–${f.bedrooms_max} BHK` : `${f.bedrooms_min} BHK`;
    before.push({ key: "bhk", text, param: ["bedrooms_min", String(f.bedrooms_min)] });
  }
  if (f.furnishing) before.push({ key: "furnishing", text: f.furnishing.replace("_", "-").replace("fully-", ""), param: ["furnishing", f.furnishing] });
  const noun: Token = f.property_type
    ? { key: "type", text: PROPERTY_NOUNS[f.property_type] ?? f.property_type, param: ["property_type", f.property_type] }
    : { key: "type", text: "homes" };
  if (f.listing_type) after.push({ key: "listing", text: f.listing_type === "rent" ? "to rent" : "to buy", param: ["listing_type", f.listing_type] });
  if (f.locality) after.push({ key: "locality", text: `in ${f.locality}`, param: ["locality", f.locality] });
  if (f.city) after.push({ key: "city", text: f.locality ? f.city : `in ${f.city}`, prefix: f.locality ? ", " : undefined, param: ["city", f.city] });
  if (f.price_min_inr && f.price_max_inr) after.push({ key: "price", text: `${formatInr(f.price_min_inr)}–${formatInr(f.price_max_inr)}`, param: ["price_max", String(f.price_max_inr)] });
  else if (f.price_max_inr) after.push({ key: "price", text: `under ${formatInr(f.price_max_inr)}`, param: ["price_max", String(f.price_max_inr)] });
  else if (f.price_min_inr) after.push({ key: "price", text: `over ${formatInr(f.price_min_inr)}`, param: ["price_min", String(f.price_min_inr)] });
  if (f.pet_policy) after.push({ key: "pets", text: "where pets are allowed", param: ["pet_policy", f.pet_policy] });
  if (f.amenities.length) after.push({ key: "amenities", text: `with ${f.amenities.map((a) => a.replace(/_/g, " ")).join(" and ")}` });
  f.near.forEach((n) => after.push({ key: `near:${n}`, text: `near ${n === "it_park" ? "an IT park" : `a ${n.replace("_", " ")}`}` }));
  if (f.soft_preferences.length) after.push({ key: "feel", text: `that feel ${f.soft_preferences.map((p) => `“${p}”`).join(", ")}` });
  return { before, noun, after };
}

/** What the AI understood, as an editable sentence. Removing a part re-runs a plain filter search (no AI call). */
export default function FilterChips({ filters, count }: { filters: InterpretedFilters; count: number }) {
  const navigate = useNavigate();
  const { before, noun, after } = sentence(filters);
  const all = [...before, noun, ...after];

  const remove = (removed: Token) => {
    const params = new URLSearchParams();
    all.filter((t) => t.key !== removed.key && t.param).forEach((t) => params.append(t.param![0], t.param![1]));
    if (removed.key !== "amenities") filters.amenities.forEach((a) => params.append("amenities", a));
    navigate(`/search?${params.toString()}`);
  };

  const renderToken = (token: Token) => (
    <span key={token.key}>
    {token.prefix ?? " "}
    <button
      type="button"
      onClick={() => remove(token)}
      className="understood group inline cursor-pointer [box-decoration-break:clone] hover:decoration-danger"
      aria-label={`Remove “${token.text}” from the search`}
      title="Remove from search"
    >
      {token.text}
      <span aria-hidden className="ml-1 hidden text-base font-normal text-slate group-hover:inline group-focus-visible:inline">×</span>
    </button>
    </span>
  );

  return (
    <p className="max-w-4xl text-xl leading-loose text-slate sm:text-2xl" aria-live="polite">
      <span className="font-semibold text-ink">{count === 1 ? "1 match" : `${count}${count >= 20 ? "+" : ""} matches`}</span>
      {" for"}
      {before.map(renderToken)}
      {noun.param ? renderToken(noun) : <span className="font-semibold text-ink"> {noun.text}</span>}
      {after.map(renderToken)}
    </p>
  );
}
