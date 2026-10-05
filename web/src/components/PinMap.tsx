import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { MAP_STYLE } from "./MapView";

interface Props {
  lat: number | null;
  lng: number | null;
  /** Fallback centre when there is no pin yet, as [lng, lat]. */
  centre: [number, number];
  /** Present → the pin can be placed by clicking and moved by dragging (listing editor). */
  onChange?: (lat: number, lng: number) => void;
  label: string;
}

/** One map pin: shows where a home is (listing page) or lets an agent place it (editor). */
export default function PinMap({ lat, lng, centre, onChange, label }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);
  const changeRef = useRef(onChange);
  changeRef.current = onChange;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: MAP_STYLE,
        center: lat !== null && lng !== null ? [lng, lat] : centre,
        zoom: lat !== null ? 15 : 11,
        attributionControl: { compact: true },
        cooperativeGestures: !onChange, // on the listing page, scrolling the page shouldn't zoom the map
      });
    } catch {
      setFailed(true); // no WebGL: the editor still has the latitude/longitude fields
      return;
    }
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    if (onChange) instance.on("click", (e) => changeRef.current?.(+e.lngLat.lat.toFixed(6), +e.lngLat.lng.toFixed(6)));
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
      marker.current = null;
    };
    // Created once; pin moves are handled below.
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    if (lat === null || lng === null) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    if (!marker.current) {
      marker.current = new maplibregl.Marker({ color: "#1c2757", draggable: !!onChange }).setLngLat([lng, lat]).addTo(instance);
      marker.current.on("dragend", () => {
        const p = marker.current!.getLngLat();
        changeRef.current?.(+p.lat.toFixed(6), +p.lng.toFixed(6));
      });
      instance.jumpTo({ center: [lng, lat], zoom: Math.max(instance.getZoom(), 14) });
    } else {
      marker.current.setLngLat([lng, lat]);
    }
  }, [lat, lng, onChange]);

  if (failed) {
    return <p className="rounded-lg border border-rule bg-paper p-4 text-sm text-slate" role="status">The map couldn't load on this device{onChange ? " — enter the latitude and longitude below instead" : ""}.</p>;
  }
  return <div ref={container} role="region" aria-label={label} className="h-64 w-full overflow-hidden rounded-lg border border-rule bg-rule/40" />;
}
