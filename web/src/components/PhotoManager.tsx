import { useState } from "react";

import { del, put } from "../lib/api";
import type { Listing, ListingImage } from "../lib/types";

/** FR-1.2: the first photo is the cover and the search thumbnail. Move buttons keep reordering keyboard-usable. */
export default function PhotoManager({ listingId, images, onChange, onError }: {
  listingId: string; images: ListingImage[]; onChange: (listing: Listing) => void; onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const run = async (action: () => Promise<Listing>, done: string) => {
    setBusy(true);
    try {
      onChange(await action());
      setStatus(done);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const move = (from: number, to: number) => {
    const ids = images.map((i) => i.id);
    const [moved] = ids.splice(from, 1);
    ids.splice(to, 0, moved);
    void run(() => put<Listing>(`/listings/${listingId}/images/order`, { image_ids: ids }),
      to === 0 ? "Cover photo changed." : `Photo moved to position ${to + 1}.`);
  };

  if (images.length === 0) return null;
  return (
    <div className="space-y-2">
      <ol className="grid grid-cols-2 gap-3">
        {images.map((img, i) => (
          <li key={img.id} className="space-y-1">
            <div className="relative overflow-hidden rounded-md border border-rule">
              <img src={img.thumb_url} alt={img.caption ?? `Photo ${i + 1}`} className="aspect-[4/3] w-full object-cover" />
              {i === 0 && <span className="absolute left-1 top-1 rounded bg-ink px-1.5 text-xs font-semibold text-paper">Cover</span>}
            </div>
            <div className="flex flex-wrap gap-x-3 text-sm">
              {i > 0 && <button type="button" disabled={busy} onClick={() => move(i, i - 1)} className="link text-sm" aria-label={`Move photo ${i + 1} earlier`}>Earlier</button>}
              {i < images.length - 1 && <button type="button" disabled={busy} onClick={() => move(i, i + 1)} className="link text-sm" aria-label={`Move photo ${i + 1} later`}>Later</button>}
              {i > 0 && <button type="button" disabled={busy} onClick={() => move(i, 0)} className="link text-sm" aria-label={`Make photo ${i + 1} the cover`}>Make cover</button>}
              <button type="button" disabled={busy} className="text-sm font-medium text-danger hover:underline" aria-label={`Delete photo ${i + 1}`}
                onClick={() => run(() => del<Listing>(`/listings/${listingId}/images/${img.id}`), "Photo deleted.")}>Delete</button>
            </div>
          </li>
        ))}
      </ol>
      <p className="sr-only" role="status" aria-live="polite">{status}</p>
    </div>
  );
}
