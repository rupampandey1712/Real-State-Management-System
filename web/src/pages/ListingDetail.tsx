import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import FavouriteButton from "../components/FavouriteButton";
import { PhotoPlaceholder } from "../components/ListingCard";
import QAPanel from "../components/QAPanel";
import { api, newIdempotencyKey, post } from "../lib/api";
import { useAIFeatures } from "../lib/features";
import type { Listing } from "../lib/types";

const PinMap = lazy(() => import("../components/PinMap"));

const words = (value: string) => value.replace(/_/g, " ");
const sqft = (n: number | null) => n && `${n.toLocaleString("en-IN")} sq ft`;
const factId = (label: string) => `fact-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

/** Labels match the AI fact sheet (listing service to_facts), so a Q&A citation can point at its row. */
function Facts({ listing, highlight }: { listing: Listing; highlight: string | null }) {
  const rows: [string, string | number | null][] = [
    ["Bedrooms (BHK)", `${listing.bedrooms} BHK`],
    ["Property type", words(listing.property_type)],
    ["Bathrooms", listing.bathrooms],
    ["Balconies", listing.balconies],
    ["Carpet area", sqft(listing.carpet_area_sqft)],
    ["Built-up area", sqft(listing.builtup_area_sqft)],
    ["Floor", listing.floor !== null && listing.total_floors ? `${listing.floor} of ${listing.total_floors}` : null],
    ["Facing", listing.facing && words(listing.facing).replace(" ", "-")],
    ["Furnishing", listing.furnishing && words(listing.furnishing)],
    ["Covered parking", listing.parking_covered || null],
    ["Open parking", listing.parking_open || null],
    ["Maintenance per month", listing.maintenance && `${listing.maintenance.display} a month`],
    ["Security deposit", listing.deposit?.display ?? null],
    ["Pets", listing.pet_policy === "unknown" ? null : words(listing.pet_policy)],
    ["Possession", listing.possession && words(listing.possession)],
    ["Age of property", listing.property_age_years !== null ? `${listing.property_age_years} years` : null],
    ["RERA registration", listing.rera_id],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
      {rows.filter(([, v]) => v !== null && v !== "" && v !== 0).map(([k, v]) => (
        <div key={k} id={factId(k)} className={`border-t border-rule py-3 transition-colors ${highlight === k ? "bg-haldi-wash" : ""}`}>
          <dt className="text-sm text-slate">{k === "Bedrooms (BHK)" ? "Bedrooms" : k}</dt>
          <dd className="text-lg font-semibold first-letter:uppercase">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Gallery({ listing }: { listing: Listing }) {
  const [index, setIndex] = useState(0);
  const images = listing.images;
  const current = images[index];
  return (
    <div className="space-y-2">
      <div className={`overflow-hidden rounded-lg ${current ? "aspect-[16/9]" : "aspect-[16/9] sm:aspect-[3/1]"}`}>
        {current ? <img src={current.url} alt={current.caption ?? `Photo ${index + 1} of ${images.length}`} className="h-full w-full object-cover" />
          : <PhotoPlaceholder locality={listing.locality} city={listing.city} bedrooms={listing.bedrooms} large />}
      </div>
      {images.length > 1 && (
        <ul className="flex gap-2 overflow-x-auto pb-1" aria-label={`All ${images.length} photos`}>
          {images.map((img, i) => (
            <li key={img.id} className="shrink-0">
              <button type="button" onClick={() => setIndex(i)} aria-label={`Show photo ${i + 1}${img.caption ? `: ${img.caption}` : ""}`}
                aria-current={i === index} className={`block overflow-hidden rounded-md border-2 ${i === index ? "border-ink" : "border-transparent"}`}>
                <img src={img.thumb_url} alt="" className="h-16 w-24 object-cover" loading="lazy" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EnquiryForm({ listingId, prefill }: { listingId: string; prefill: string }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  // One key per form: a double submit or retry sends the same key, so only one enquiry is created.
  const idempotencyKey = useRef(newIdempotencyKey());
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setState("sending");
    try {
      await post(`/listings/${listingId}/enquiries`, {
        name: form.get("name"), email: form.get("email"), phone: form.get("phone") || null,
        message: form.get("message"), source: prefill ? "qa_unknown" : "listing_page", consent: form.get("consent") === "on",
      }, { idempotencyKey: idempotencyKey.current });
      setState("sent");
    } catch {
      setState("error");
    }
  };
  if (state === "sent") {
    return (
      <div id="enquiry" className="rounded-lg border border-leaf/30 bg-paper p-5">
        <p className="text-lg font-semibold text-leaf">Message sent to the agent.</p>
        <p className="text-slate">They'll reply to the email address you gave.</p>
      </div>
    );
  }
  return (
    <form id="enquiry" onSubmit={submit} className="space-y-3 rounded-lg border border-rule bg-paper p-5">
      <h2 className="text-xl font-bold">Message the agent</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="field-label">Name<input name="name" required maxLength={100} autoComplete="name" className="field mt-1" /></label>
        <label className="field-label">Email<input name="email" type="email" required autoComplete="email" className="field mt-1" /></label>
      </div>
      <label className="field-label">Phone (optional)<input name="phone" autoComplete="tel" className="field mt-1" /></label>
      <label className="field-label">Message
        <textarea key={prefill} name="message" required maxLength={2000} rows={3}
          defaultValue={prefill || "I'd like to know more about this home."} className="field mt-1" />
      </label>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" name="consent" required className="mt-1 size-4 shrink-0 accent-ink" />
        <span>I agree to share my name, email and phone with this listing's agent so they can reply to me. <Link to="/privacy" className="link text-sm">How we use your details</Link></span>
      </label>
      <button disabled={state === "sending"} className="btn-primary w-full">{state === "sending" ? "Sending…" : "Send message"}</button>
      {state === "error" && <p className="text-sm text-danger" role="alert">The message didn't send. Check your details and try again.</p>}
      <p className="text-sm text-slate">Only this listing's agent sees your details. They're never sent to AI features.</p>
    </form>
  );
}

export default function ListingDetail() {
  const { id = "" } = useParams();
  const [prefill, setPrefill] = useState("");
  const [highlight, setHighlight] = useState<string | null>(null);
  const features = useAIFeatures();
  const { data: listing, isLoading, error } = useQuery({ queryKey: ["listing", id], queryFn: () => api<Listing>(`/listings/${id}`) });

  if (isLoading) return <p className="text-xl text-slate">Loading this home…</p>;
  if (error || !listing) {
    return (
      <div className="space-y-2">
        <p className="text-xl font-semibold">This listing isn't available.</p>
        <p className="text-slate">It may have been sold, rented or taken down. <Link to="/search" className="link">Find similar homes</Link></p>
      </div>
    );
  }

  const askAgent = (question: string) => {
    setPrefill(`I asked the assistant: "${question}". Could you tell me?`);
    document.getElementById("enquiry")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const showFact = (label: string) => {
    const target = document.getElementById(factId(label)) ?? document.getElementById(label === "Amenities" ? "amenities" : "listing-header");
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlight(label);
    window.setTimeout(() => setHighlight(null), 2500);
  };

  return (
    <article className="space-y-8">
      <Gallery listing={listing} />

      <div className="grid gap-10 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-8">
          <header id="listing-header" className="space-y-1">
            <div className="flex items-start justify-between gap-4">
              <p className="text-display font-extrabold tabular-nums tracking-tight">
                {listing.price.display}
                {listing.listing_type === "rent" && <span className="text-2xl font-semibold text-slate"> a month</span>}
              </p>
              <div className="pt-3"><FavouriteButton listingId={listing.id} /></div>
            </div>
            <h1 className="text-2xl font-bold">{listing.title}</h1>
            <p className="text-lg text-slate">{listing.locality}, {listing.city}{listing.pincode ? ` ${listing.pincode}` : ""}</p>
            {listing.rera_id && <p className="text-sm text-slate">RERA registration: <span className="font-semibold text-ink">{listing.rera_id}</span></p>}
          </header>

          <Facts listing={listing} highlight={highlight} />

          {listing.description && (
            <section className="space-y-2">
              <h2 className="text-xl font-bold">About this home</h2>
              <p className="max-w-[65ch] whitespace-pre-line text-lg leading-relaxed">{listing.description}</p>
            </section>
          )}

          {listing.amenities.length > 0 && (
            <section id="amenities" className={`space-y-3 ${highlight === "Amenities" ? "rounded-md bg-haldi-wash p-2" : ""}`}>
              <h2 className="text-xl font-bold">In the building</h2>
              <ul className="flex flex-wrap gap-2">
                {listing.amenities.map((a) => (
                  <li key={a} className="rounded-md border border-rule bg-paper px-3 py-1 first-letter:uppercase">{words(a)}</li>
                ))}
              </ul>
            </section>
          )}

          {listing.lat !== null && listing.lng !== null && (
            <section className="space-y-3">
              <h2 className="text-xl font-bold">Where it is</h2>
              <Suspense fallback={<div className="h-64 animate-pulse rounded-lg bg-rule/50" />}>
                <PinMap lat={listing.lat} lng={listing.lng} centre={[listing.lng, listing.lat]}
                  label={`Map showing the home's location in ${listing.locality}, ${listing.city}`} />
              </Suspense>
              <p className="text-sm text-slate">The pin is placed by the agent. Confirm the exact address with them.</p>
            </section>
          )}
        </div>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          {features.listing_qa && <QAPanel listingId={listing.id} onAskAgent={askAgent} onShowFact={showFact} />}
          <EnquiryForm listingId={listing.id} prefill={prefill} />
        </aside>
      </div>
    </article>
  );
}
