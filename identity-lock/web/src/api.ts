/**
 * Typed client for the read-only Identity Lock API.
 *
 * The shapes here mirror `identitylock.api.app`. They are hand-written rather than
 * generated: the surface is six endpoints, and a generator would add a build step
 * to a project whose whole point is that it runs from a clean checkout.
 */

export interface Aggregates {
  n_total: number
  n_accepted: number
  identity_mean: number
  identity_std: number
  identity_p05: number
  identity_min: number
  identity_max: number
  margin_mean: number | null
  technical_mean: number
  consistency_rate: number
  diversity: number
  drift_slope: number
  drift_r2: number
  drift_p_value: number
  identity_ci_low: number
  identity_ci_high: number
}

export interface RunSummary {
  run_id: string
  label: string
  suite_id: string
  character: { id: string; name: string; disclosure: string }
  recipe: { id: string; name: string; revision: string }
  created_at: string
  embedder: string
  provider: string
  passed: boolean
  failed_gates: string[]
  aggregates: Aggregates
  n_selected: number
}

export interface Gate {
  name: string
  passed: boolean
  observed: number | null
  threshold: number | null
  detail: string
}

export interface CandidateMetrics {
  identity_similarity: number
  nearest_reference: number
  identity_margin: number | null
  impostor_best: number | null
  impostor_id: string | null
  technical_score: number
  frame: { width: number; height: number; sharpness: number; exposure: number; contrast: number }
}

export interface Candidate {
  id: string
  prompt_id: string
  prompt: string
  seed: number
  decision: 'accept' | 'reject'
  selected: boolean
  rejections: string[]
  metrics: CandidateMetrics
  image: string | null
}

export interface RunDetail extends RunSummary {
  gates: Gate[]
  candidates: Candidate[]
  manifest: Record<string, unknown>
  suite: {
    id: string
    description: string
    cohort_ids: string[]
    prompts: { id: string; text: string; tags: string[] }[]
    seeds: number[]
    recipe: Record<string, unknown>
  }
}

export interface ComparisonSummary {
  comparison_id: string
  metric: string
  baseline_run_id: string
  baseline_label: string
  challenger_run_id: string
  challenger_label: string
  win_rate: number
  mean_delta: number
  ci_low: number
  ci_high: number
  effect_size: number
  n_pairs: number
  outcome: 'improvement' | 'regression' | 'inconclusive'
  rationale: string
}

export interface ComparisonDetail extends ComparisonSummary {
  pairs: { prompt_id: string; seed: number; baseline: number; challenger: number; delta: number }[]
  gates: Gate[]
}

export interface Health {
  status: string
  version: string
  workdir: string
  runs: number
  comparisons: number
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`${path} → ${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => get<Health>('api/health'),
  runs: () => get<RunSummary[]>('api/runs'),
  run: (id: string) => get<RunDetail>(`api/runs/${encodeURIComponent(id)}`),
  comparisons: () => get<ComparisonSummary[]>('api/comparisons'),
  comparison: (id: string) => get<ComparisonDetail>(`api/comparisons/${encodeURIComponent(id)}`),
}
