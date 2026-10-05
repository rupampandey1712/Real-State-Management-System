import { post } from "./api";

// Anonymous product events for the success metrics (requirements §9; services/engagement/app/product_metrics.py).
// No user id, email or listing content — only a random id per browser tab and the event's own fields.

export type SearchMode = "ai" | "fallback" | "classic";

type ProductEvent =
  | { type: "search_performed"; mode: SearchMode }
  | { type: "listing_viewed"; from_search: boolean; mode?: SearchMode }
  | { type: "listing_published"; minutes_to_publish: number }
  | { type: "description_saved"; edit_ratio: number }
  | { type: "qa_session" }
  | { type: "enquiry_sent"; after_qa: boolean };

function sessionId(): string {
  const fresh = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, "0")).join("");
  try {
    const existing = sessionStorage.getItem("estate.session");
    if (existing) return existing;
    const id = fresh();
    sessionStorage.setItem("estate.session", id);
    return id;
  } catch {
    return fresh(); // storage blocked: still count the event, just not linked to the tab
  }
}

/** Fire-and-forget: a lost event never affects the user. */
export function track(event: ProductEvent): void {
  void post("/events", { ...event, session: sessionId() }).catch(() => undefined);
}

/** Share of the AI draft's words the agent changed before saving (word-level edit distance / longer length). */
export function editRatio(draft: string, final: string): number {
  const a = draft.split(/\s+/).filter(Boolean);
  const b = final.split(/\s+/).filter(Boolean);
  if (!a.length && !b.length) return 0;
  let previous = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) {
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    previous = current;
  }
  return Math.min(1, Math.round((previous[b.length] / Math.max(a.length, b.length)) * 1000) / 1000);
}
