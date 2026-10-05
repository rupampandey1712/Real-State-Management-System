// API types. Mirror the Pydantic schemas in services/*; replace with OpenAPI-generated types (task T0.7).

export interface Money {
  amount_minor: number;
  currency: string;
  display: string;
}

export interface User {
  id: string;
  email: string;
  name: string | null;
  role: "buyer" | "agent" | "admin";
  agent_verified: boolean;
  agent_requested_at?: string | null;
}

export interface AdminUser extends User {
  phone: string | null;
  agency_name: string | null;
  rera_agent_id: string | null;
  suspended_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  detail?: string | null;
  reason: string;
  admin_id: string;
  created_at: string;
}

export interface SearchItem {
  id: string;
  title: string;
  listing_type: "sale" | "rent";
  property_type: string;
  price: Money;
  bedrooms: number;
  bathrooms: number | null;
  carpet_area_sqft: number | null;
  locality: string;
  city: string;
  lat: number | null;
  lng: number | null;
  thumbnail_url: string | null;
  match: { score: number; reasons: string[] };
}

export interface InterpretedFilters {
  is_property_query: boolean;
  city: string | null;
  locality: string | null;
  listing_type: "sale" | "rent" | null;
  property_type: string | null;
  bedrooms_min: number | null;
  bedrooms_max: number | null;
  price_min_inr: number | null;
  price_max_inr: number | null;
  furnishing: string | null;
  pet_policy: string | null;
  amenities: string[];
  near: string[];
  soft_preferences: string[];
  assumptions: string[];
}

export interface SearchResponse {
  items: SearchItem[];
  next_cursor: string | null;
  interpreted_filters: InterpretedFilters | null;
  assumptions: string[];
  is_property_query: boolean;
  meta: { mode?: "ai" | "fallback" | "classic"; cached?: boolean; ai_request_id?: string | null; sort?: string };
}

export interface ListingImage {
  id: string;
  url: string;
  thumb_url: string;
  caption: string | null;
  position: number;
}

export interface Listing {
  id: string;
  agent_id: string;
  status: string;
  listing_type: "sale" | "rent";
  property_type: string;
  title: string;
  description: string | null;
  description_ai: boolean;
  price: Money;
  deposit: Money | null;
  maintenance: Money | null;
  bedrooms: number;
  bathrooms: number | null;
  balconies: number | null;
  carpet_area_sqft: number | null;
  builtup_area_sqft: number | null;
  floor: number | null;
  total_floors: number | null;
  facing: string | null;
  furnishing: string | null;
  parking_covered: number;
  parking_open: number;
  pet_policy: string;
  possession: string | null;
  property_age_years: number | null;
  amenities: string[];
  address_line: string;
  locality: string;
  city: string;
  pincode: string | null;
  lat: number | null;
  lng: number | null;
  rera_id: string | null;
  images: ListingImage[];
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListingSummary {
  id: string;
  status: string;
  title: string;
  description_ai: boolean;
  price: Money;
  bedrooms: number;
  locality: string;
  city: string;
  thumbnail_url: string | null;
  documents_count: number;
  updated_at: string;
}

export interface DescribeResponse {
  title: string;
  description: string;
  highlights: string[];
  warnings: string[];
  ai_request_id: string;
}

export interface Citation {
  id: string;
  type: "listing_field" | "document";
  label: string;
  /** The field's value, or the passage of the document the answer came from (FR-5.2). */
  excerpt?: string;
}

export interface ImproveResponse {
  description: string;
  warnings: string[];
  ai_request_id: string;
}

export type AIFeatures = Record<"nl_search" | "ai_describe" | "ai_improve" | "listing_qa", boolean>;

export interface FlagState {
  enabled: boolean;
  overridden: boolean;
  default: boolean;
  description: string;
}

export interface AIMetricRow {
  day: string;
  feature: string;
  requests: number;
  errors: number;
  error_rate: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_cost_usd: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  thumbs_up: number;
  thumbs_down: number;
}

export interface FeedbackItem {
  id: string;
  feature: string;
  created_at: string;
  listing_id: string | null;
  prompt_id: string;
  prompt_version: number;
  model: string;
  status: string;
  request_redacted: string | null;
  response_redacted: string | null;
  feedback: number;
  feedback_comment: string | null;
}

export interface AdminListing {
  id: string;
  agent_id: string;
  status: string;
  title: string;
  locality: string;
  city: string;
  price: Money;
  updated_at: string;
  last_action: AuditEntry | null;
}

export interface Favourite {
  listingId: string;
  createdAt: string;
}

export interface SavedSearch {
  id: string;
  name: string;
  raw_query: string | null;
  filters: Record<string, string>;
  createdAt: string;
}

export interface ListingDocument {
  id: string;
  filename: string;
  kind: string;
  status: "uploaded" | "processing" | "ready" | "failed";
  error: string | null;
  created_at: string;
}
