import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import DescriptionGenerator from "../components/DescriptionGenerator";
import ImproveText from "../components/ImproveText";
import PhotoManager from "../components/PhotoManager";
import { editRatio, track } from "../lib/analytics";
import { ApiError, api, del, download, newIdempotencyKey, patch, post } from "../lib/api";
import { useAIFeatures } from "../lib/features";
import type { Listing, ListingDocument } from "../lib/types";

const PinMap = lazy(() => import("../components/PinMap"));

const AMENITIES = ["lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
  "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting"];
const CITY_CENTRES: Record<string, [number, number]> = { Pune: [73.8567, 18.5204], Bengaluru: [77.5946, 12.9716], Mumbai: [72.8777, 19.076] };

type Form = Record<string, string | number | boolean | string[] | null>;

const EMPTY: Form = {
  listing_type: "sale", property_type: "apartment", title: "", description: "", price_inr: "", maintenance_inr: "",
  deposit_inr: "", bedrooms: 2, bathrooms: 2, balconies: "", carpet_area_sqft: "", builtup_area_sqft: "", floor: "",
  total_floors: "", facing: "", furnishing: "", parking_covered: 0, parking_open: 0, pet_policy: "unknown",
  possession: "ready_to_move", property_age_years: "", amenities: [], address_line: "", locality: "", city: "Pune",
  pincode: "", lat: "", lng: "", rera_id: "", description_ai: false,
};

const NUMERIC = ["price_inr", "maintenance_inr", "deposit_inr", "bedrooms", "bathrooms", "balconies", "carpet_area_sqft",
  "builtup_area_sqft", "floor", "total_floors", "parking_covered", "parking_open", "property_age_years", "lat", "lng"];

/** Field-level messages for the error envelope's details (FR-1 AC: highlight each missing field). */
const ISSUE_TEXT: Record<string, string> = {
  required: "Needed before you can publish.",
  too_short_min_50_characters: "Write at least 50 characters.",
  required_for_under_construction_projects: "Projects under construction must show their RERA number.",
  set_both_latitude_and_longitude: "Place the pin on the map (or enter both coordinates).",
};

const STATUS_NOTE: Record<string, string> = {
  removed: "A moderator took this listing down. It's hidden from buyers and can't be edited. Contact support to have it reviewed.",
  suspended: "Your account is suspended, so this listing is hidden from buyers.",
};

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

function issueText(issue: string): string {
  if (ISSUE_TEXT[issue]) return ISSUE_TEXT[issue];
  if (issue.startsWith("discriminatory_wording")) return `Remove wording that excludes or prefers people: “${issue.split(": ").slice(1).join(": ")}”.`;
  return issue.replace(/^Value error, /, "").replace(/_/g, " ");
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
  const features = useAIFeatures();
  const existing = useQuery({ queryKey: ["listing", id], queryFn: () => api<Listing>(`/listings/${id}`), enabled: !!id });
  const [form, setForm] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<string[]>([]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const createKey = useRef(newIdempotencyKey()); // a double-clicked "Save draft" creates one listing, not two
  const aiDraft = useRef<string | null>(null); // the AI text the agent accepted, to measure how much they edited it
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

  const status = existing.data?.status;
  const locked = status === "removed" || status === "suspended";
  const set = (key: string, value: Form[string]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setFieldErrors((e) => (key in e ? Object.fromEntries(Object.entries(e).filter(([k]) => k !== key)) : e));
  };
  const errorFor = (key: string) => fieldErrors[key] && (
    <span id={`${key}-error`} className="mt-1 block text-sm font-medium text-danger">{fieldErrors[key]}</span>
  );
  const invalid = (key: string) => (fieldErrors[key] ? { "aria-invalid": true, "aria-describedby": `${key}-error` } : {});
  const input = (key: string, label: string, props: Record<string, unknown> = {}) => (
    <label className="field-label">{label}
      <input name={key} value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)}
        className={`field mt-1 ${fieldErrors[key] ? "border-danger" : ""}`} {...invalid(key)} {...props} />
      {errorFor(key)}
    </label>
  );
  const select = (key: string, label: string, options: [string, string][]) => (
    <label className="field-label">{label}
      <select name={key} value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)}
        className={`field mt-1 ${fieldErrors[key] ? "border-danger" : ""}`} {...invalid(key)}>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
      {errorFor(key)}
    </label>
  );

  const showErrors = (e: unknown) => {
    const err = e as ApiError;
    if (err.details?.length) {
      const byField = Object.fromEntries(err.details.map((d) => [d.field, issueText(d.issue)]));
      setFieldErrors(byField);
      setErrors([`${err.message} (${err.details.length} ${err.details.length === 1 ? "item" : "items"} highlighted)`]);
      const first = document.querySelector<HTMLElement>(`[name="${err.details[0].field}"]`);
      first?.focus();
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      setErrors([err.message]);
    }
  };

  const save = async (event?: FormEvent) => {
    event?.preventDefault();
    setErrors([]);
    setFieldErrors({});
    setNotice(null);
    try {
      const listing = id
        ? await patch<Listing>(`/listings/${id}`, toPayload(form))
        : await post<Listing>("/listings", toPayload(form), { idempotencyKey: createKey.current });
      await queryClient.invalidateQueries({ queryKey: ["listing", listing.id] });
      if (aiDraft.current !== null && form.description_ai) {
        track({ type: "description_saved", edit_ratio: editRatio(aiDraft.current, String(form.description ?? "")) });
        aiDraft.current = null; // one measurement per accepted draft
      }
      setNotice("Saved.");
      if (!id) navigate(`/agent/listings/${listing.id}/edit`, { replace: true });
      return listing;
    } catch (e) {
      showErrors(e);
    }
  };

  const action = async (request: () => Promise<Listing>, done: string, after?: (result: Listing) => void) => {
    if (!id) return;
    setErrors([]);
    try {
      const result = await request();
      await existing.refetch();
      setNotice(done);
      after?.(result);
    } catch (e) {
      showErrors(e);
    }
  };

  const publish = async () => {
    if (!id || !(await save())) return;
    try {
      const firstPublish = !existing.data?.published_at;
      await post(`/listings/${id}/publish`);
      if (firstPublish && existing.data) {
        track({ type: "listing_published", minutes_to_publish: Math.round((Date.now() - Date.parse(existing.data.created_at)) / 600) / 100 });
      }
      navigate(`/listings/${id}`);
    } catch (e) {
      showErrors(e);
    }
  };

  const upload = async (kind: "images" | "documents", files: FileList | null) => {
    if (!id || !files) return;
    const failures: string[] = [];
    for (const file of Array.from(files)) {
      const body = new FormData();
      body.append("file", file);
      try {
        await api(`/listings/${id}/${kind}`, { method: "POST", body });
      } catch (e) {
        failures.push(`${file.name}: ${(e as Error).message}`);
      }
    }
    setErrors(failures);
    await Promise.all([existing.refetch(), kind === "documents" ? documents.refetch() : null]);
    if (failures.length < files.length) {
      setNotice(kind === "documents" ? "Document uploaded. It will be ready for buyer questions in a minute or two." : "Photos added.");
    }
  };

  const removeDocument = async (doc: ListingDocument) => {
    try {
      await del(`/listings/${id}/documents/${doc.id}`);
      await documents.refetch();
      setNotice(`${doc.filename} removed. The assistant no longer answers from it.`);
    } catch (e) {
      showErrors(e);
    }
  };

  const rent = form.listing_type === "rent";
  const amenities = form.amenities as string[];
  const possessionMode = form.possession === "ready_to_move" || form.possession === "under_construction" ? String(form.possession) : "date";
  const lat = form.lat === "" || form.lat === null ? null : Number(form.lat);
  const lng = form.lng === "" || form.lng === null ? null : Number(form.lng);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/agent/listings" className="link text-sm">My listings</Link>
          <h1 className="text-title font-extrabold tracking-tight">{id ? form.title || "Edit listing" : "Add a listing"}</h1>
        </div>
        {existing.data && (
          <p className="text-slate">
            Status: <span className="font-semibold text-ink">{existing.data.status}</span>
            {existing.data.description_ai && <span className="ml-3 rounded bg-haldi-wash px-1.5 text-sm font-semibold text-ink">AI-assisted description</span>}
          </p>
        )}
      </div>
      {status && STATUS_NOTE[status] && <p className="rounded-md border border-danger/30 bg-paper p-4 text-danger" role="status">{STATUS_NOTE[status]}</p>}

      <div className="grid gap-10 lg:grid-cols-[1fr_24rem]">
        <form onSubmit={save} className="space-y-8">
          <fieldset disabled={locked} className="space-y-8">
            <Group title="The basics">
              {select("listing_type", "Listing for", [["sale", "Sale"], ["rent", "Rent"]])}
              {select("property_type", "Property type", [["apartment", "Apartment"], ["independent_house", "Independent house"], ["villa", "Villa"], ["plot", "Plot"], ["commercial", "Commercial"]])}
              <label className="field-label">Possession
                <select name="possession" value={possessionMode} {...invalid("possession")}
                  onChange={(e) => set("possession", e.target.value === "date" ? new Date().toISOString().slice(0, 7) : e.target.value)}
                  className={`field mt-1 ${fieldErrors.possession ? "border-danger" : ""}`}>
                  <option value="ready_to_move">Ready to move</option>
                  <option value="under_construction">Under construction</option>
                  <option value="date">From a date</option>
                </select>
                {errorFor("possession")}
              </label>
              {possessionMode === "date" && input("possession", "Possession from (month)", { type: "month" })}
              {possessionMode === "ready_to_move" && input("property_age_years", "Age of property (years)", { type: "number", min: 0, max: 150 })}
            </Group>

            <Group title="Price" hint="In rupees. Buyers see it as lakh or crore.">
              {input("price_inr", rent ? "Rent per month" : "Price", { type: "number", required: true, min: 1, inputMode: "numeric" })}
              {input("maintenance_inr", "Maintenance per month", { type: "number", min: 0, inputMode: "numeric" })}
              {rent && input("deposit_inr", "Security deposit", { type: "number", min: 0, inputMode: "numeric" })}
            </Group>

            <Group title="Size and layout">
              {input("bedrooms", "Bedrooms (BHK)", { type: "number", min: 0, max: 20, required: true })}
              {input("bathrooms", "Bathrooms", { type: "number", min: 0 })}
              {input("balconies", "Balconies", { type: "number", min: 0, max: 10 })}
              {input("carpet_area_sqft", "Carpet area (sq ft)", { type: "number", min: 1 })}
              {input("builtup_area_sqft", "Built-up area (sq ft)", { type: "number", min: 1 })}
              {select("furnishing", "Furnishing", [["", "Not specified"], ["unfurnished", "Unfurnished"], ["semi_furnished", "Semi-furnished"], ["fully_furnished", "Fully furnished"]])}
              {input("floor", "Floor", { type: "number" })}
              {input("total_floors", "Floors in building", { type: "number", min: 0 })}
              {select("facing", "Facing", [["", "Not specified"], ["north", "North"], ["south", "South"], ["east", "East"], ["west", "West"], ["north_east", "North-east"], ["north_west", "North-west"], ["south_east", "South-east"], ["south_west", "South-west"]])}
              {input("parking_covered", "Covered parking spots", { type: "number", min: 0, max: 10 })}
              {input("parking_open", "Open parking spots", { type: "number", min: 0, max: 10 })}
              {select("pet_policy", "Pets", [["unknown", "Not specified"], ["allowed", "Allowed"], ["not_allowed", "Not allowed"]])}
            </Group>

            <Group title="Location" hint="The street address is never shown to AI features.">
              {select("city", "City", [["Pune", "Pune"], ["Bengaluru", "Bengaluru"], ["Mumbai", "Mumbai"]])}
              {input("locality", "Locality", { required: true, placeholder: "Kharadi" })}
              {input("pincode", "Pincode", { pattern: "\\d{6}", inputMode: "numeric" })}
              <div className="sm:col-span-2">{input("address_line", "Building and street", { required: true })}</div>
              {input("rera_id", form.possession !== "ready_to_move" && !rent ? "RERA number (required)" : "RERA number")}
              <div className="space-y-2 sm:col-span-3">
                <p className="field-label">Map pin <span className="font-normal">— click the map to place it, then drag to adjust. Buyers see it on the map.</span></p>
                <Suspense fallback={<div className="h-64 animate-pulse rounded-lg bg-rule/50" />}>
                  <PinMap lat={lat} lng={lng} centre={CITY_CENTRES[String(form.city)] ?? CITY_CENTRES.Pune}
                    onChange={(la, ln) => { set("lat", la); set("lng", ln); }} label="Map for placing the listing's pin" />
                </Suspense>
                <div className="grid gap-4 sm:grid-cols-3">
                  {input("lat", "Latitude", { type: "number", step: "any", min: -90, max: 90 })}
                  {input("lng", "Longitude", { type: "number", step: "any", min: -180, max: 180 })}
                  {lat !== null && (
                    <button type="button" onClick={() => { set("lat", ""); set("lng", ""); }} className="self-end text-sm font-medium text-slate hover:text-danger">Remove pin</button>
                  )}
                </div>
              </div>
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
                <textarea name="description" value={String(form.description ?? "")} {...invalid("description")}
                  onChange={(e) => { set("description", e.target.value); set("description_ai", false); }}
                  rows={7} maxLength={5000} className={`field mt-1 ${fieldErrors.description ? "border-danger" : ""}`} />
                {errorFor("description")}
                {errorFor("title")}
              </label>
            </fieldset>
          </fieldset>

          <div className="sticky bottom-0 -mx-5 flex flex-wrap items-center gap-3 border-t border-rule bg-wash/95 px-5 py-4 backdrop-blur">
            {!locked && <button type="submit" className="btn-quiet">{id ? "Save changes" : "Save draft"}</button>}
            {id && !locked && status !== "published" && <button type="button" onClick={publish} className="btn-primary">Save and publish</button>}
            {status === "published" && (
              <button type="button" onClick={() => action(() => post<Listing>(`/listings/${id}/unpublish`), "Listing hidden. It no longer appears in search; publish again any time.")} className="btn-quiet text-danger">Unpublish</button>
            )}
            {id && (
              <button type="button" className="btn-quiet"
                onClick={() => action(() => post<Listing>(`/listings/${id}/duplicate`), "Copy created.", (copy) => navigate(`/agent/listings/${copy.id}/edit`))}>
                Duplicate
              </button>
            )}
            {id && !confirmArchive && <button type="button" onClick={() => setConfirmArchive(true)} className="text-sm font-medium text-slate hover:text-danger">Archive</button>}
            {id && confirmArchive && (
              <span className="flex items-center gap-2 text-sm">
                Archive removes it from search and your list for good.
                <button type="button" className="btn-quiet py-1 text-danger"
                  onClick={() => action(() => post<Listing>(`/listings/${id}/archive`), "Archived.", () => navigate("/agent/listings"))}>Yes, archive</button>
                <button type="button" onClick={() => setConfirmArchive(false)} className="font-medium text-slate">Cancel</button>
              </span>
            )}
            {notice && <p className="text-leaf" role="status">{notice}</p>}
            {errors.length > 0 && (
              <ul className="w-full text-danger" role="alert">{errors.map((e) => <li key={e} className="first-letter:uppercase">{e}</li>)}</ul>
            )}
          </div>
        </form>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          {id && !locked ? (
            <>
              {features.ai_describe && (
                <DescriptionGenerator listingId={id} onAccept={({ title, description }) => {
                  setForm((f) => ({ ...f, title, description, description_ai: true }));
                  aiDraft.current = description;
                  setNotice("Draft added to the form. Review it, then save.");
                }} />
              )}
              {features.ai_improve && (
                <ImproveText listingId={id} text={String(form.description ?? "")} onAccept={(description) => {
                  setForm((f) => ({ ...f, description, description_ai: true }));
                  aiDraft.current = description;
                  setNotice("Rewrite added to the form. Review it, then save.");
                }} />
              )}
              <section className="space-y-4 rounded-lg border border-rule bg-paper p-5">
                <div className="space-y-2">
                  <h2 className="text-xl font-bold">Photos</h2>
                  <p className="text-[0.95rem] text-slate">{existing.data?.images.length ?? 0} of 30 added. JPEG, PNG, WebP or HEIC, up to 15 MB each. Location data is removed.</p>
                  <input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple
                    onChange={(e) => upload("images", e.target.files)} aria-label="Add photos"
                    className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink file:px-3 file:py-1.5 file:font-semibold file:text-paper" />
                  {existing.data && (
                    <PhotoManager listingId={id} images={existing.data.images} onError={(m) => setErrors([m])}
                      onChange={(l) => queryClient.setQueryData(["listing", id], l)} />
                  )}
                </div>
                <div className="border-t border-rule pt-4">
                  <h2 className="text-xl font-bold">Documents for buyer questions</h2>
                  <p className="text-[0.95rem] text-slate">Society rules, brochures or floor plans as PDF (up to 10, 20 MB each). The assistant answers from these; buyers never get the files.</p>
                  <input type="file" accept="application/pdf" onChange={(e) => upload("documents", e.target.files)} aria-label="Add a PDF document"
                    className="mt-2 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-ink file:px-3 file:py-1.5 file:font-semibold file:text-paper" />
                  {(documents.data?.length ?? 0) > 0 && (
                    <ul className="mt-3 space-y-2" aria-live="polite">
                      {documents.data!.map((d) => (
                        <li key={d.id} className="text-[0.95rem]">
                          <span className="font-medium">{d.filename}</span>
                          <span className={`ml-2 text-sm font-semibold ${DOC_STATUS[d.status].className}`}>{DOC_STATUS[d.status].label}</span>
                          <span className="ml-3 inline-flex gap-3 text-sm">
                            <button type="button" className="link text-sm" onClick={() => download(`/listings/${id}/documents/${d.id}/file`, d.filename).catch((e) => setErrors([(e as Error).message]))}>Download</button>
                            <button type="button" className="font-medium text-danger hover:underline" onClick={() => removeDocument(d)}>Remove</button>
                          </span>
                          {d.error && <p className="text-sm text-danger">{d.error}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            </>
          ) : !id ? (
            <p className="rounded-lg border border-rule bg-paper p-5 text-slate">
              Save the draft first. Then you can add photos and documents and have the AI write the description.
            </p>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
