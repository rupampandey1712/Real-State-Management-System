import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl, { type LngLatBoundsLike } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { SearchMode } from "../lib/analytics";
import type { SearchItem } from "../lib/types";

// OpenFreeMap: free OpenStreetMap vector tiles, no API key and no usage limits (docs/decisions/0018).
export const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const CITY_CENTRES: Record<string, [number, number]> = {
  Pune: [73.8567, 18.5204],
  Bengaluru: [77.5946, 12.9716],
  Mumbai: [72.8777, 19.076],
};
const INDIA: LngLatBoundsLike = [[72.6, 12.7], [78.0, 19.4]];

export function boundsToBbox(bounds: maplibregl.LngLatBounds): string {
  const f = (n: number) => n.toFixed(5);
  return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map(f).join(",");
}

interface Props {
  items: SearchItem[];
  bbox: string | null;
  city: string | null;
  onSearchArea: (bbox: string) => void;
  searchMode?: SearchMode;
}

/** Results on a map (FR-2.3). The list stays the primary, keyboard-first view (NFR-6); each pin is a
 *  focusable button that opens its listing. "Search this area" re-runs the search inside the visible box. */
export default function MapView({ items, bbox, city, onSearchArea, searchMode }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const navigate = useNavigate();
  const [moved, setMoved] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const initial = bbox?.split(",").map(Number);
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: MAP_STYLE,
        bounds: initial?.length === 4 ? [[initial[0], initial[1]], [initial[2], initial[3]]] : undefined,
        center: initial ? undefined : CITY_CENTRES[city ?? ""] ?? [76.0, 16.0],
        zoom: initial ? undefined : city ? 11 : 5,
        maxBounds: [[66, 6], [90, 30]],
        attributionControl: { compact: true },
      });
    } catch {
      setFailed(true); // no WebGL (old device, locked-down or headless browser): the list still works
      return;
    }
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // Only user gestures count as "moved", not our own fitBounds below.
    instance.on("moveend", (event) => { if ((event as { originalEvent?: unknown }).originalEvent) setMoved(true); });
    instance.on("error", (event) => { if (String(event.error?.message ?? "").includes("style")) setFailed(true); });
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
    // The map is created once; bbox/city changes are handled by fitting bounds below.
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    markers.current.forEach((m) => m.remove());
    const pinned = items.filter((i) => i.lat !== null && i.lng !== null);
    markers.current = pinned.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "rounded-full border-2 border-paper bg-ink px-2 py-0.5 text-sm font-bold text-paper shadow hover:bg-ink-soft focus-visible:outline-haldi";
      button.textContent = item.price.display.replace("₹", "₹ ");
      button.setAttribute("aria-label", `${item.bedrooms} BHK in ${item.locality}, ${item.price.display}. Open listing`);
      button.addEventListener("click", () => navigate(`/listings/${item.id}`, { state: searchMode ? { fromSearch: searchMode } : undefined }));
      return new maplibregl.Marker({ element: button }).setLngLat([item.lng!, item.lat!]).addTo(instance);
    });
    if (!bbox && pinned.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      pinned.forEach((i) => bounds.extend([i.lng!, i.lat!]));
      instance.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
    } else if (!bbox && pinned.length === 0 && !city) {
      instance.fitBounds(INDIA, { duration: 0 });
    }
    setMoved(false);
  }, [items, bbox, city, navigate, searchMode]);

  const unpinned = items.filter((i) => i.lat === null || i.lng === null).length;

  return (
    <div className="relative">
      {failed && <p className="mb-2 text-sm text-danger" role="status">The map couldn't load. The list of homes still works.</p>}
      <div ref={container} hidden={failed} className="h-[28rem] w-full overflow-hidden rounded-lg border border-rule bg-rule/40 sm:h-[34rem]"
        role="region" aria-label="Map of the homes in these results. The list of homes has the same results." />
      {moved && (
        <button type="button" onClick={() => map.current && onSearchArea(boundsToBbox(map.current.getBounds()))}
          className="btn-primary absolute left-1/2 top-3 -translate-x-1/2 shadow-lg">
          Search this area
        </button>
      )}
      {unpinned > 0 && (
        <p className="mt-2 text-sm text-slate">
          {unpinned === 1 ? "1 home has" : `${unpinned} homes have`} no map pin yet and {unpinned === 1 ? "appears" : "appear"} only in the list.
        </p>
      )}
    </div>
  );
}
