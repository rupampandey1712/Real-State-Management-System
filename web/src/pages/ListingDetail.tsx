import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import FavouriteButton from "../components/FavouriteButton";
import { PhotoPlaceholder } from "../components/ListingCard";
import QAPanel from "../components/QAPanel";
import { api, newIdempotencyKey, post } from "../lib/api";
import type { Listing } from "../lib/types";

const words = (value: string) => value.replace(/_/g, " ");

function Facts({ listing }: { listing: Listing }) {
  const rows: [string, string | number | null][] = [
    ["Bedrooms", `${listing.bedrooms} BHK`],
    ["Bathrooms", listing.bathrooms],
    ["Carpet area", listing.carpet_area_sqft && `${listing.carpet_area_sqft.toLocaleString("en-IN")} sq ft`],
    ["Floor", listing.floor !== null && listing.total_floors ? `${listing.floor} of ${listing.total_floors}` : null],
    ["Facing", listing.facing && words(listing.facing)],
    ["Furnishing", listing.furnishing && words(listing.furnishing)],
    ["Covered parking", listing.parking_covered || null],
    ["Maintenance", listing.maintenance && `${listing.maintenance.display} a month`],
    ["Deposit", listing.deposit?.display ?? null],
    ["Pets", listing.pet_policy === "unknown" ? null : words(listing.pet_policy)],
    ["Possession", listing.possession && words(listing.possession)],
    ["RERA number", listing.rera_id],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
      {rows.filter(([, v]) => v !== null && v !== "" && v !== 0).map(([k, v]) => (
        <div key={k} className="border-t border-rule py-3">
          <dt className="text-sm text-slate">{k}</dt>
          <dd className="text-lg font-semibold first-letter:uppercase">{v}</dd>
        </div>
      ))}
    </dl>
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
        message: form.get("message"), source: prefill ? "qa_unknown" : "listing_page",
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
      <button disabled={state === "sending"} className="btn-primary w-full">{state === "sending" ? "Sending…" : "Send message"}</button>
      {state === "error" && <p className="text-sm text-danger">The message didn't send. Check your details and try again.</p>}
      <p className="text-sm text-slate">Only this listing's agent sees your details.</p>
    </form>
  );
}

export default function ListingDetail() {
  const { id = "" } = useParams();
  const [prefill, setPrefill] = useState("");
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

  const [cover, ...rest] = listing.images;
  return (
    <article className="space-y-8">
      <div className={`grid gap-2 ${rest.length ? "sm:grid-cols-[2fr_1fr]" : ""}`}>
        <div className={`overflow-hidden rounded-lg ${cover ? "aspect-[16/10]" : "aspect-[16/9] sm:aspect-[3/1]"}`}>
          {cover ? <img src={cover.url} alt={cover.caption ?? "Main photo"} className="h-full w-full object-cover" />
            : <PhotoPlaceholder locality={listing.locality} city={listing.city} bedrooms={listing.bedrooms} large />}
        </div>
        {rest.length > 0 && (
          <div className="hidden grid-rows-2 gap-2 sm:grid">
            {rest.slice(0, 2).map((img) => (
              <img key={img.id} src={img.url} alt={img.caption ?? ""} className="h-full w-full rounded-lg object-cover" />
            ))}
          </div>
        )}
      </div>

      <div className="grid gap-10 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-8">
          <header className="space-y-1">
            <div className="flex items-start justify-between gap-4">
            <p className="text-display font-extrabold tabular-nums tracking-tight">
              {listing.price.display}
              {listing.listing_type === "rent" && <span className="text-2xl font-semibold text-slate"> a month</span>}
            </p>
            <div className="pt-3"><FavouriteButton listingId={listing.id} /></div>
            </div>
            <h1 className="text-2xl font-bold">{listing.title}</h1>
            <p className="text-lg text-slate">{listing.locality}, {listing.city}</p>
          </header>

          <Facts listing={listing} />

          {listing.description && (
            <section className="space-y-2">
              <h2 className="text-xl font-bold">About this home</h2>
              <p className="max-w-[65ch] whitespace-pre-line text-lg leading-relaxed">{listing.description}</p>
            </section>
          )}

          {listing.amenities.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-xl font-bold">In the building</h2>
              <ul className="flex flex-wrap gap-2">
                {listing.amenities.map((a) => (
                  <li key={a} className="rounded-md border border-rule bg-paper px-3 py-1 first-letter:uppercase">{words(a)}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <QAPanel listingId={listing.id} onAskAgent={askAgent} />
          <EnquiryForm listingId={listing.id} prefill={prefill} />
        </aside>
      </div>
    </article>
  );
}
