/** Miroir des schémas Pydantic du backend (backend/jobradar/schemas/*). Les dates arrivent en ISO 8601 (UTC). */

export type UserStatus = "new" | "seen" | "saved" | "applied" | "ignored";
export type LifecycleStatus = "listed" | "stale" | "deadline_passed" | "closed";
export type WorkMode = "onsite" | "hybrid" | "remote";

export interface Freshness {
  age_days: number | null;
  label: "fresh" | "recent" | "old" | "unknown_date";
  first_seen_age_days: number;
}

export interface OfferListItem {
  id: number;
  title: string;
  company_name: string | null;
  location: string | null;
  country: string | null;
  city: string | null;
  work_mode: WorkMode | null;
  contract_type: string | null;
  experience_level: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  application_deadline: string | null;
  lifecycle_status: LifecycleStatus;
  freshness: Freshness;
  score: number | null;
  score_profile_id: number | null;
  score_profile_name: string | null;
  user_status: UserStatus;
  primary_url: string;
  sources: { key: string; name: string; url: string }[];
  estimated_fields: string[];
  remote_eligibility: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
}

export interface OfferSourceLink {
  source_key: string;
  source_name: string;
  original_url: string;
  source_job_id: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
  published_text: string | null;
  attribution: string | null;
  same_as_urls: string[];
}

export interface ScoreComponent {
  label: string;
  points: number;
  /** Points possibles pour ce critère (0 si non applicable : critère absent du profil ou information manquante). */
  max: number;
  applicable: boolean;
  detail: unknown;
}

export interface ScoreExplanation {
  matched_keywords: string[];
  missing: string[];
  excluded: string[];
  restrictions: string[];
  notes: string[];
  coverage: number;
  [key: string]: unknown;
}

export interface OfferScore {
  profile_id: number;
  profile_name: string;
  score: number;
  breakdown: Record<string, ScoreComponent>;
  explanation: ScoreExplanation;
  computed_at: string;
}

export interface OfferDetail extends OfferListItem {
  description: string | null;
  sector: string | null;
  remote_regions: string[];
  last_verified_at: string | null;
  notes: string | null;
  saved_at: string | null;
  source_links: OfferSourceLink[];
  scores: OfferScore[];
  content_hash: string;
}

export interface OfferPage {
  items: OfferListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ManualOfferInput {
  url: string;
  title: string;
  company_name?: string | null;
  location?: string | null;
  description?: string | null;
  contract_type?: string | null;
  work_mode?: WorkMode | null;
  notes?: string | null;
}

export interface Profile {
  id: number;
  name: string;
  description: string | null;
  countries: string[];
  cities: string[];
  positive_keywords: string[];
  keyword_groups: Record<string, string[]>;
  excluded_keywords: string[];
  target_roles: string[];
  sectors: string[];
  contract_types: string[];
  work_modes: string[];
  experience_levels: string[];
  weights: Record<string, number> | null;
  effective_weights: Record<string, number>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type ProfileInput = Omit<Profile, "id" | "created_at" | "updated_at" | "effective_weights">;

export type SourceState = "active" | "disabled" | "to_verify" | "unreachable" | "error" | "excluded";

export interface Source {
  key: string;
  name: string;
  base_url: string;
  source_type: string;
  market: string;
  countries: string[];
  enabled: boolean;
  collection_method: string;
  verification_status: string;
  implementation: string;
  can_collect: boolean;
  decision_reason: string | null;
  tos_note: string | null;
  doc_status: string | null;
  state: SourceState;
  state_label: string;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_success_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  last_error: string | null;
  last_error_type: string | null;
  offers_count: number;
  errors_count: number;
  last_run_offers_found: number | null;
  min_interval_minutes: number | null;
  configuration: Record<string, unknown>;
}

export interface SourceTestResult {
  ok: boolean;
  status: string;
  detail: string;
  http_status: number | null;
  latency_ms: number | null;
  sample_count: number | null;
  checked_at: string;
}

export interface Employer {
  key: string;
  name: string;
  sector: string | null;
  country: string | null;
  website: string | null;
  career_url: string | null;
  collection_method: string;
  source_key: string | null;
  status: string;
  checked_on: string | null;
  verification_note: string | null;
}

export type RunStatus = "queued" | "running" | "completed" | "partial" | "failed" | "interrupted";
export type RunSourceStatus = "pending" | "running" | "success" | "failed" | "skipped";

export interface RunSource {
  source_key: string;
  source_name: string;
  status: RunSourceStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  offers_found: number;
  offers_created: number;
  offers_updated: number;
  duplicates_detected: number;
  offers_rejected: number;
  requests_made: number;
  error_type: string | null;
  error_message: string | null;
  details: Record<string, unknown>;
}

export interface Run {
  id: number;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  trigger_type: "manual" | "scheduled";
  status: RunStatus;
  profile_id: number | null;
  profile_name: string | null;
  sources_requested: number;
  sources_succeeded: number;
  sources_failed: number;
  offers_found: number;
  offers_created: number;
  offers_updated: number;
  duplicates_detected: number;
  error_summary: string | null;
  sources: RunSource[];
  source_keys: string[];
}

export interface RunPage {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
}

export interface SchedulerSettings {
  enabled: boolean;
  interval_minutes: number;
  profile_ids: number[] | null;
  source_keys: string[] | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: number | null;
  last_run_status: string | null;
  last_error: string | null;
  alive: boolean;
  state: "disabled" | "running" | "stopped";
  heartbeat_at: string | null;
  mode: "embedded" | "off";
  this_process_is_leader: boolean;
  min_interval_minutes: number;
  max_interval_minutes: number;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: string;
  scheduler: { state: SchedulerSettings["state"]; alive: boolean; mode: string };
  time: string;
}

export interface Meta {
  contract_types: string[];
  work_modes: WorkMode[];
  experience_levels: string[];
  user_statuses: UserStatus[];
  lifecycle_statuses: LifecycleStatus[];
  countries: Record<string, string>;
  sectors: Record<string, string>;
  weights: { default: Record<string, number>; labels: Record<string, string> };
}

export interface Dashboard {
  total_offers: number;
  new_offers: number;
  saved_offers: number;
  applied_offers: number;
  recently_detected_7d: number;
  detected_24h: number;
  active_sources: number;
  total_connectors: number;
  sources_in_error: { key: string; name: string; state: string; error: string | null; error_type: string | null }[];
  last_run: {
    id: number;
    status: RunStatus;
    started_at: string;
    finished_at: string | null;
    trigger_type: string;
    offers_found: number;
    offers_created: number;
    duplicates_detected: number;
    sources_failed: number;
  } | null;
  scheduler: Omit<SchedulerSettings, "min_interval_minutes" | "max_interval_minutes" | "last_run_status">;
  by_source: { source: string; key: string; count: number }[];
  by_sector: { sector: string; count: number }[];
  by_profile: { profile: string; count: number }[];
  by_work_mode: { work_mode: string; count: number }[];
  top_matches: OfferListItem[];
  recent: OfferListItem[];
}
