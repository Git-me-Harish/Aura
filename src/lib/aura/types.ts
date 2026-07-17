/**
 * AURA — TypeScript types mirroring the FastAPI backend schemas.
 * Keep this in sync with aura-backend/app/models/schemas.py.
 */

export type AgentName =
  | "orchestrator"
  | "preference"
  | "context"
  | "memory"
  | "knowledge"
  | "recommendation"
  | "rl"
  | "explanation"
  | "safety";

export interface User {
  user_id: string;
  name: string;
  timezone: string;
  preferred_language: string;
}

export interface ContextSnapshot {
  timestamp: string;
  time_of_day: "morning" | "afternoon" | "evening" | "night";
  weekday: string;
  weather: string;
  temperature_c: number;
  location: string;
  device: string;
  mood: string;
  recent_searches: string[];
  calendar_next: string | null;
  raw: Record<string, any>;
}

export interface PreferenceProfile {
  top_interests: string[];
  favorite_categories: string[];
  interaction_patterns: Record<string, number>;
  long_term_vector: number[];
  updated_at: string;
}

export interface MemoryRecord {
  record_id: string;
  user_id: string;
  kind: string;
  content: string;
  embedding: number[];
  metadata: Record<string, any>;
  timestamp: string;
}

export interface RecommendationItem {
  item_id: string;
  title: string;
  category: string;
  description: string;
  score: number;
  source: "cf" | "neural_cf" | "hybrid" | "gnn" | "llm_rank";
  reasons: string[];
  metadata: Record<string, any>;
}

export interface Explanation {
  item_id: string;
  why_recommended: string;
  why_not_alternatives: string;
  confidence: number;
  contributing_factors: string[];
}

export interface SafetyVerdict {
  item_id: string;
  passed: boolean;
  bias_flag: boolean;
  unsafe_flag: boolean;
  hallucination_flag: boolean;
  privacy_flag: boolean;
  policy_flag: boolean;
  notes: string;
}

export interface UserAction {
  event_id: string;
  user_id: string;
  item_id: string;
  action: "click" | "purchase" | "like" | "skip" | "session_end";
  reward: number;
  timestamp: string;
  context: Record<string, any>;
}

export interface PolicySnapshot {
  version: string;
  mean_reward: number;
  samples: number;
  epsilon: number;
  updated_at: string;
}

export interface AgentTrace {
  agent: AgentName;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  input_summary: string;
  output_summary: string;
  artifacts: Record<string, any>;
}

export interface OrchestrationResult {
  request_id: string;
  user_id: string;
  started_at: string;
  finished_at: string;
  trace: AgentTrace[];
  recommendations: RecommendationItem[];
  explanations: Explanation[];
  safety_verdicts: SafetyVerdict[];
  policy_version: string;
}

export interface AgentStatus {
  name: AgentName;
  role: string;
  status: "idle" | "thinking" | "ready" | "error";
  last_run: string | null;
  latency_ms: number | null;
  detail: string;
}

export interface MCPTool {
  name: string;
  category: string;
  connected: boolean;
  last_sync: string | null;
  description: string;
  capabilities: string[];
}

export interface MCPToolCall {
  tool: string;
  method: string;
  args: Record<string, any>;
  result: any;
  duration_ms: number;
}

export interface RecommendationMetrics {
  precision_at_k: number;
  recall_at_k: number;
  ndcg: number;
  map_score: number;
  mrr: number;
}

export interface BusinessMetrics {
  ctr: number;
  conversion_rate: number;
  revenue: number;
  retention: number;
  avg_session_time_sec: number;
}

export interface RLMetrics {
  cumulative_reward: number;
  policy_regret: number;
  reward_growth: number;
  samples_seen: number;
  policy_version: string;
}

export interface DashboardMetrics {
  recommendation: RecommendationMetrics;
  business: BusinessMetrics;
  rl: RLMetrics;
}
