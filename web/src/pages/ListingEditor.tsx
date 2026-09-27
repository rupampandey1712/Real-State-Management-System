import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import DescriptionGenerator from "../components/DescriptionGenerator";
import { ApiError, api, newIdempotencyKey, patch, post } from "../lib/api";
import type { Listing, ListingDocument } from "../lib/types";

const AMENITIES = ["lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
  "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting"];

type Form = Record<string, string | number | boolean | string[] | null>;

const EMPTY: Form = {
  listing_type: "sale", property_type: "apartment", title: "", description: "", price_inr: "", maintenance_inr: "",
  deposit_inr: "", bedrooms: 2, bathrooms: 2, carpet_area_sqft: "", builtup_area_sqft: "", floor: "", total_floors: "",
  facing: "", furnishing: "", parking_covered: 0, pet_policy: "unknown", possession: "ready_to_move", amenities: [],
  address_line: "", locality: "", city: "Pune", pincode: "", rera_id: "", description_ai: false,
};

const NUMERIC = ["price_inr", "maintenance_inr", "deposit_inr", "bedrooms", "bathrooms", "carpet_area_sqft",
  "builtup_area_sqft", "floor", "total_floors", "parking_covered"];

function fromListing(l: Listing): Form {
  return {
    ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).filter((k) => k in l).map((k) => [k, (l as unknown as Form)[k] ?? ""])),
    price_inr: l.price.amount_minor / 100,
    maintenance_inr: l.maintenance ? l.maintenance.amount_minor / 100 : "",
    deposit_inr: l.deposit ? l.deposit.amount_minor / 100 : "",
  };
}

function toPayload(form: Form): Record<string, unknown> {
  return Object.fromEntries(Object.entries(form).map(([k, v]) => {
    if (v === "") return [k, null];
    return [k, NUMERIC.includes(k) ? Number(v) : v];
  }));
}

const DOC_STATUS: Record<ListingDocument["status"], { label: string; className: string }> = {
  uploaded: { label: "Waiting", className: "text-slate" },
  processing: { label: "Reading…", className: "text-slate" },
  ready: { label: "Ready for questions", className: "text-leaf" },
  failed: { label: "Couldn't read", className: "text-danger" },
};

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="border-t border-rule pt-5">
      <legend className="float-left mb-3 w-full">
        <span className="text-lg font-bold">{title}</span>
        {hint && <span className="block text-sm text-slate">{hint}</span>}
      </legend>
      <div className="clear-both grid gap-4 sm:grid-cols-3">{children}</div>
    </fieldset>
  );
}

export default function ListingEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const existing = useQuery({ queryKey: ["listing", id], queryFn: () => api<Listing>(`/listings/${id}`), enabled: !!id });
  const [form, setForm] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const createKey = useRef(newIdempotencyKey()); // a double-clicked "Save draft" creates one listing, not two
  const documents = useQuery({
    queryKey: ["documents", id],
    queryFn: () => api<ListingDocument[]>(`/listings/${id}/documents`),
    enabled: !!id,
    // Poll while any PDF is still being read by the AI service; stop once all are ready or failed.
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "uploaded" || d.status === "processing") ? 4000 : false),
  });

  useEffect(() => {
    if (existing.data) setForm(fromListing(existing.data));
  }, [existing.data]);

  const set = (key: string, value: Form[string]) => setForm((f) => ({ ...f, [key]: value }));
  const input = (key: string, label: string, props: Record<string, unknown> = {}) => (
    <label className="field-label">{label}
      <input value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)} className="field mt-1" {...props} />
    </label>
  );
  const select = (key: string, label: string, options: [string, string][]) => (
    <label className="field-label">{label}
      <select value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)} className="field mt-1">
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </label>
  );

  const save = async (event?: FormEvent) => {
    event?.preventDefault();
    setErrors([]);
    setNotice(null);
    try {
      const listing = id
        ? await patch<Listing>(`/listings/${id}`, toPayload(form))
        : await post<Listing>("/listings", toPayload(form), { idempotencyKey: createKey.current });
      await queryClient.invalidateQueries({ queryKey: ["listing", listing.id] });
      setNotice("Saved.");
      if (!id) navigate(`/agent/listings/${listing.id}/edit`, { replace: true });
      return listing;
    } catch (e) {
      const err = e as ApiError;
      setErrors(err.details?.length ? err.details.map((d) => `${d.field.replace(/_/g, " ")}: ${d.issue.replace(/_/g, " ")}`) : [err.message]);
    }
  };

  const publish = async () => {
    if (!id || !(await save())) return;
    try {
      await post(`/listings/${id}/publish`);
      navigate(`/listings/${id}`);
    } catch (e) {
      setErrors([(e as Error).message]);
    }
  };

  const unpublish = async () => {
    if (!id) return;
    try {
      await post(`/listings/${id}/unpublish`);
      await existing.refetch();
      setNotice("Listing hidden. It no longer appears in search; publish again any time.");
    } catch (e) {
      setErrors([(e as Error).message]);
    }
  };

  const upload = async (kind: "images" | "documents", files: FileList | null) => {
    if (!id || !files) return;
    for (const file of Array.from(files)) {
      const body = new FormData();
      body.append("file", file);
      try {
        await api(`/listings/${id}/${kind}`, { method: "POST", body });
      } catch (e) {
        setErrors([(e as Error).message]);
      }
    }
    await Promise.all([existing.refetch(), kind === "documents" ? documents.refetch() : null]);
    setNotice(kind === "documents" ? "Document uploaded. It will be ready for buyer questions in a minute or two." : "Photos added.");
  };

  const rent = form.listing_type === "rent";
  const amenities = form.amenities as string[];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/agent/listings" className="link text-sm">My listings</Link>
          <h1 className="text-title font-extrabold tracking-tight">{id ? form.title || "Edit listing" : "Add a listing"}</h1>
        </div>
        {existing.data && <p className="text-slate">Status: <span className="font-semibold text-ink">{existing.data.status}</span></p>}
      </div>

      <div className="grid gap-10 lg:grid-cols-[1fr_24rem]">
        <form onSubmit={save} className="space-y-8">
          <Group title="The basics">
            {select("listing_type", "Listing for", [["sale", "Sale"], ["rent", "Rent"]])}
            {select("property_type", "Property type", [["apartment", "Apartment"], ["independent_house", "Independent house"], ["villa", "Villa"], ["plot", "Plot"], ["commercial", "Commercial"]])}
            {select("possession", "Possession", [["ready_to_move", "Ready to move"], ["under_construction", "Under construction"]])}
          </Group>

          <Group title="Price" hint="In rupees. Buyers see it as lakh or crore.">
            {input("price_inr", rent ? "Rent per month" : "Price", { type: "number", required: true, min: 1, inputMode: "numeric" })}
            {input("maintenance_inr", "Maintenance per month", { type: "number", min: 0, inputMode: "numeric" })}
            {rent && input("deposit_inr", "Security deposit", { type: "number", min: 0, inputMode: "numeric" })}
          </Group>

          <Group title="Size and layout">
            {input("bedrooms", "Bedrooms (BHK)", { type: "number", min: 0, max: 20, required: true })}
            {input("bathrooms", "Bathrooms", { type: "number", min: 0 })}
            {input("parking_covered", "Covered parking spots", { type: "number", min: 0 })}
            {input("carpet_area_sqft", "Carpet area (sq ft)", { type: "number", min: 1 })}
            {input("builtup_area_sqft", "Built-up area (sq ft)", { type: "number", min: 1 })}
            {select("furnishing", "Furnishing", [["", "Not specified"], ["unfurnished", "Unfurnished"], ["semi_furnished", "Semi-furnished"], ["fully_furnished", "Fully furnished"]])}
            {input("floor", "Floor", { type: "number" })}
            {input("total_floors", "Floors in building", { type: "number", min: 0 })}
            {select("facing", "Facing", [["", "Not specified"], ["north", "North"], ["south", "South"], ["east", "East"], ["west", "West"], ["north_east", "North-east"], ["north_west", "North-west"], ["south_east", "South-east"], ["south_west", "South-west"]])}
            {select("pet_policy", "Pets", [["unknown", "Not specified"], ["allowed", "Allowed"], ["not_allowed", "Not allowed"]])}
          </Group>

          <Group title="Location" hint="The street address is never shown to AI features.">
            {select("city", "City", [["Pune", "Pune"], ["Bengaluru", "Bengaluru"], ["Mumbai", "Mumbai"]])}
            {input("locality", "Locality", { required: true, placeholder: "Kharadi" })}
            {input("pincode", "Pincode", { pattern: "\\d{6}", inputMode: "numeric" })}
            <div className="sm:col-span-2">{input("address_line", "Building and street", { required: true })}</div>
            {input("rera_id", "RERA number")}
          </Group>

          <fieldset className="border-t border-rule pt-5">
            <legend className="mb-3 text-lg font-bold">In the building</legend>
            <div className="flex flex-wrap gap-2">
              {AMENITIES.map((a) => {
                const on = amenities.includes(a);
                return (
                  <button type="button" key={a} aria-pressed={on}
                    onClick={() => set("amenities", on ? amenities.filter((x) => x !== a) : [...amenities, a])}
                    className={`rounded-md border px-3 py-1.5 first-letter:uppercase ${on ? "border-ink bg-ink text-paper" : "border-rule bg-paper text-ink hover:border-ink"}`}>
                    {a.replace(/_/g, " ")}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <fieldset className="space-y-4 border-t border-rule pt-5">
            <legend className="mb-3 text-lg font-bold">Title and description</legend>
            {input("title", "Title (10–120 characters)", { required: true, minLength: 10, maxLength: 120 })}
            <label className="field-label">Description
              <textarea value={String(form.description ?? "")} onChange={(e) => { set("description", e.target.value); set("description_ai", false); }}
                rows={7} maxLength={5000} className="field mt-1" />
            </label>
          </fieldset>

          <div className="sticky bottom-0 -mx-5 flex flex-wrap items-center gap-3 border-t border-rule bg-wash/95 px-5 py-4 backdrop-blur">
            <button type="submit" className="btn-quiet">{id ? "Save changes" : "Save draft"}</button>
            {id && existing.data?.status !== "published" && <button type="button" onClick={publish} className="btn-primary">Save and publish</button>}
            {existing.data?.status === "published" && (
              <button type="button" onClick={unpublish} className="btn-quiet text-danger">Unpublish</button>
            )}
            {notice && <p className="text-leaf" role="status">{notice}</p>}
            {errors.length > 0 && (
              <ul className="w-full text-danger" role="alert">{errors.map((e) => <li key={e} className="first-letter:uppercase">{e}</li>)}</ul>
            )}
          </div>
        </form>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          {id ? (
            <>
              <DescriptionGenerator listingId={id} onAccept={({ title, description }) => {
                setForm((f) => ({ ...f, title, description, description_ai: true }));
                setNotice("Draft added to the form. Review it, then save.");
              }} />
              <section className="space-y-4 rounded-lg border border-rule bg-paper p-5">
                <div>
                  <h2 className="text-xl font-bold">Photos</h2>
                  <p className="text-[0.95rem] text-slate">{existing.data?.images.length ?? 0} added. JPEG, PNG or WebP, up to 15 MB each. Location data is removed.</p>
                  <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(e) => upload("images", e.target.files)}
                    className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink file:px-3 file:py-1.5 file:font-semibold file:text-paper" />
                </div>
                <div className="border-t border-rule pt-4">
                  <h2 className="text-xl font-bold">Documents for buyer questions</h2>
                  <p className="text-[0.95rem] text-slate">Society rules, brochures or floor plans as PDF. The assistant answers from these.</p>
                  <input type="file" accept="application/pdf" onChange={(e) => upload("documents", e.target.files)}
                    className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink file:px-3 file:py-1.5 file:font-semibold file:text-paper" />
                  {(documents.data?.length ?? 0) > 0 && (
                    <ul className="mt-3 space-y-2" aria-live="polite">
                      {documents.data!.map((d) => (
                        <li key={d.id} className="text-[0.95rem]">
                          <span className="font-medium">{d.filename}</span>
                          <span className={`ml-2 text-sm font-semibold ${DOC_STATUS[d.status].className}`}>{DOC_STATUS[d.status].label}</span>
                          {d.error && <p className="text-sm text-danger">{d.error}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            </>
          ) : (
            <p className="rounded-lg border border-rule bg-paper p-5 text-slate">
              Save the draft first. Then you can add photos and documents and have the AI write the description.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
