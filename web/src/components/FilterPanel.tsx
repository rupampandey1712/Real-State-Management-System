import { useState, type FormEvent } from "react";

import { formatInr } from "./FilterChips";

export const AMENITIES = ["lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
  "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting"];

const CITIES: Record<string, string[]> = {
  Pune: ["Kharadi", "Baner", "Hinjewadi", "Wakad", "Viman Nagar", "Kothrud"],
  Bengaluru: ["Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Hebbal"],
  Mumbai: ["Andheri West", "Powai", "Bandra West", "Thane West", "Goregaon East"],
};

/** Classic-search params this panel edits (FR-2.1). Everything else in the URL (sort, view, bbox) is kept. */
const FIELDS = ["city", "locality", "listing_type", "property_type", "bedrooms_min", "bedrooms_max",
  "price_min", "price_max", "furnishing", "pet_policy"] as const;

interface Props {
  params: URLSearchParams;
  onApply: (params: URLSearchParams) => void;
  onClose?: () => void;
}

export default function FilterPanel({ params, onApply, onClose }: Props) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(FIELDS.map((f) => [f, params.get(f) ?? ""])),
  );
  const [amenities, setAmenities] = useState<string[]>(params.getAll("amenities"));
  const set = (key: string, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const apply = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [key, value] of params.entries()) {
      if (!(FIELDS as readonly string[]).includes(key) && !["amenities", "q", "cursor"].includes(key)) next.append(key, value);
    }
    FIELDS.forEach((f) => values[f].trim() && next.set(f, values[f].trim()));
    amenities.forEach((a) => next.append("amenities", a));
    onApply(next);
  };

  const clear = () => {
    setValues(Object.fromEntries(FIELDS.map((f) => [f, ""])));
    setAmenities([]);
  };

  const select = (key: string, label: string, options: [string, string][]) => (
    <label className="field-label">{label}
      <select value={values[key]} onChange={(e) => set(key, e.target.value)} className="field mt-1">
        {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  );
  const rupees = (key: string, label: string) => (
    <label className="field-label">{label}
      <input type="number" min={0} step={1000} inputMode="numeric" value={values[key]} onChange={(e) => set(key, e.target.value)}
        className="field mt-1" aria-describedby={`${key}-hint`} />
      <span id={`${key}-hint`} className="mt-0.5 block text-xs text-slate">{values[key] ? formatInr(Number(values[key])) : "In rupees"}</span>
    </label>
  );
  const bhk: [string, string][] = [["", "Any"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5+"]];

  return (
    <form onSubmit={apply} className="space-y-5 rounded-lg border border-rule bg-paper p-5" aria-labelledby="filters-heading">
      <div className="flex items-center justify-between gap-4">
        <h2 id="filters-heading" className="text-xl font-bold">Filters</h2>
        {onClose && <button type="button" onClick={onClose} className="text-sm font-medium text-slate hover:text-ink">Close</button>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {select("city", "City", [["", "Any city"], ...Object.keys(CITIES).map((c) => [c, c] as [string, string])])}
        <label className="field-label">Locality
          <input list="localities" value={values.locality} onChange={(e) => set("locality", e.target.value)} className="field mt-1" placeholder="Any" />
          <datalist id="localities">
            {(values.city ? CITIES[values.city] ?? [] : Object.values(CITIES).flat()).map((l) => <option key={l} value={l} />)}
          </datalist>
        </label>
        {select("listing_type", "Buy or rent", [["", "Either"], ["sale", "Buy"], ["rent", "Rent"]])}
        {select("property_type", "Property type", [["", "Any"], ["apartment", "Apartment"], ["independent_house", "Independent house"], ["villa", "Villa"], ["plot", "Plot"], ["commercial", "Commercial"]])}
        {select("bedrooms_min", "Bedrooms from", bhk)}
        {select("bedrooms_max", "Bedrooms up to", bhk.map(([v, t]) => [v, v === "5" ? "5" : t]))}
        {rupees("price_min", values.listing_type === "rent" ? "Rent from (a month)" : "Price from")}
        {rupees("price_max", values.listing_type === "rent" ? "Rent up to (a month)" : "Price up to")}
        {select("furnishing", "Furnishing", [["", "Any"], ["unfurnished", "Unfurnished"], ["semi_furnished", "Semi-furnished"], ["fully_furnished", "Fully furnished"]])}
        {select("pet_policy", "Pets", [["", "Any"], ["allowed", "Pets allowed"]])}
      </div>
      <fieldset>
        <legend className="field-label mb-2">Must have</legend>
        <div className="flex flex-wrap gap-2">
          {AMENITIES.map((a) => {
            const on = amenities.includes(a);
            return (
              <button type="button" key={a} aria-pressed={on} onClick={() => setAmenities(on ? amenities.filter((x) => x !== a) : [...amenities, a])}
                className={`rounded-md border px-3 py-1 text-[0.95rem] first-letter:uppercase ${on ? "border-ink bg-ink text-paper" : "border-rule bg-paper hover:border-ink"}`}>
                {a.replace(/_/g, " ")}
              </button>
            );
          })}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <button className="btn-primary">Show homes</button>
        <button type="button" onClick={clear} className="btn-quiet">Clear filters</button>
      </div>
    </form>
  );
}
