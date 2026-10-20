export interface ModelProfile {
  id: string
  name: string
  model_name: string
  api_url: string
  key_env: string
  enabled: boolean
  enable_thinking: boolean | null
  thinking_parameter?: 'auto' | 'thinking' | 'enable_thinking'
  max_tokens: number
  credential_configured: boolean
}
export interface JobSpec {
  // Rejudge and resume specs are narrower than a generate spec: a single
  // qid/language, no model list, and a frozen execution plan.
  kind?: 'rejudge' | 'resume'
  qid?: number
  language?: string
  resume_models?: { id: string; name: string }[]
  resume_parent_job_id?: string
  workflow_version?: string
  source_mode?: 'generate' | 'candidate'
  source_candidates?: Record<string, { job_id: string; candidate_id: string }>
  qids: number[]
  model_ids: string[]
  languages: string[]
  task: 'gen' | 'trans'
  source_language: string
  num_candidates: number
  probe_count: number
  temperature: number
  probe_strategy?: 'balanced' | 'hash'
  metamorphic_checks?: boolean
  auto_testcases?: boolean
  testcase_count?: number
}
export interface Outcome {
  kind: string
  status: string
  value?: unknown
  exception_type?: string
  semantic_key?: string
  runtime_ms: number | null
  timing?: { cache_mode: string; compile_ms: number; run_ms: number | null; wall_ms: number; startup_transport_ms: number; fresh_container: boolean }
}
export interface MatrixComparison {
  qid: number; left: number; right: number; similarity: number; matches: number; total: number; differing: number
  inputs_available: boolean; notice: string
  rows: { probe_index: number; input: Record<string, unknown> | null; left: Outcome; right: Outcome; matched: boolean; reason: string }[]
}
export interface Candidate {
  id: string
  index: number
  code: string
  raw: string
  code_sha256: string
  outcomes: Outcome[]
  selected?: boolean
  centrality?: number
  validation_passed?: boolean
  corpus_passed?: boolean
  corpus_verdict?: { state: string; ac_status: string; total_testcases: number; total_correct: number; version?: string; cases_sha256?: string; runtime?: string; memory?: string }
  legacy_corpus_verdict?: { state: string; ac_status: string }
  translation_preservation?: number
  finish_reason?: string
  usage?: Record<string, unknown>
  generation_state?: 'generating' | 'succeeded' | 'failed' | 'cancelled' | 'incomplete'
  judging_state?: 'completed' | 'incomplete'
  judging_failure?: { message: string }
  generation?: { version: string; attempts: GenerationAttempt[]; in_flight?: { attempt: number; http_status: number | null; elapsed_seconds: number; response_budget_seconds: number; received_bytes: number; only_whitespace_so_far: boolean } }
  timing?: { generation_ms: number; probe_ms: number; metamorphic_ms: number; validation_ms: number; full_corpus_ms?: number }
  metamorphic?: { name: string; rule: string; base_probe_index: number; state: string; passed: boolean | null; reason?: string;
    input: Record<string, unknown>; base_outcome: Outcome; outcome: Outcome; relation_expected?: unknown }[]
  verdict: { ac_status: string; runtime: string; memory: string; total_testcases: number; total_correct: number } | null
}
export interface GenerationAttempt {
  attempt: number
  started_at: string
  duration_ms: number
  http_status: number | null
  code: string
  message: string
  suggestion: string
  finish_reason: string | null
  usage: Record<string, unknown>
  content_chars: number
  reasoning_chars: number
  response_bytes: number
  response_declared_bytes?: number | null
  response_read_complete?: boolean
  response_sha256: string
  response_body: string
  response_capture_truncated: boolean
  retry_scheduled: boolean
  retry_delay_seconds: number | null
  request_id?: string | null
  request: { endpoint: string; model: string; temperature: number; max_tokens: number; prompt_sha256: string; enable_thinking: boolean | null; thinking_control?: Record<string, unknown> }
}
export interface BehaviorMetrics {
  uncertainty: number | null
  reason?: string
  mean_pairwise_agreement: number
  behavior_groups: number
  probe_count: number
  matrix: number[][]
}
export interface ResultGroup {
  behavior_semantics_version?: string
  sql_evidence?: SQLExecutionEvidence
  source_sql_evidence?: SQLExecutionEvidence
  interface?: string
  source_code?: string
  source_language?: string
  source_snapshot?: { origin: string; job_id: string; job_title: string; candidate_id: string; code_sha256: string; model_name: string; input_contract?: { sha256: string; provenance: string }; contract_binding?: string }
  judging_state?: 'completed' | 'incomplete'
  judging_error?: string
  answer_evidence?: { evidence_level: string; constraint_evidence?: string; reference_languages: string[]; limitations?: string[];
    oracle_scope?: { max_rows?: number; max_text_length?: number; max_total_text_length?: number; version?: string; description?: string };
    statement_revision?: { version: string; source: { url: string; retrieved_at: string; official_html_sha256: string } };
    execution_protocol?: { version: string; callback_scope: string; clock: string | null } }
  correctness_evidence?: CorrectnessEvidence
  qid: number
  model_id: string
  model_name: string
  language: string
  candidates: Candidate[]
  metrics: BehaviorMetrics | null
  local_pass_rate?: number | null
  validation_count: number
  corpus_count?: number
  validation_pass_rate?: number | null
  corpus_evidence?: { scope: string; evidence_level: string; notice: string; generated_count?: number }
  probe_count?: number
  probe_selection?: ProbeSelection
  selection_advice?: SelectionAdvice
}
export interface SQLExecutionEvidence {
  dialect: string
  environment: { version: string; mysql_version: string; image: string; client: string; network: string; sql_mode: string; collation: string }
  reference_gate_status: string
  reference_case_count: number
  reference_source_sha256: string
  cases_sha256: string
  limitations: string[]
}
export interface SelectionAdvice {
  version: string
  state: 'incomplete' | 'abstained' | 'recommended'
  candidate_id: string | null
  candidate_index: number | null
  eligible_count: number
  behavior_center_id: string | null
  same_as_behavior_center: boolean | null
  validation_count: number
  reason: string
  notice: string
  provenance: 'derived_from_saved_evidence' | 'frozen_at_run'
  rejected: { candidate_id: string; candidate_index: number; reason_codes: string[]; reasons: string[] }[]
}
export interface ProbeSelection {
  version: string
  strategy: 'balanced' | 'hash'
  requested_probe_count: number
  actual_probe_count: number
  unique_legal_input_count: number
  validation_count: number
  features_available: number
  features_covered: number
  warnings: string[]
  answers_used_for_selection: boolean
  private_validation_count?: number
  selected: { input_sha256: string; features: string[]; new_features: string[] }[]
}
export interface LabJob {
  evidence_advisories?: { id: string; qid: number; cases_sha256: string; reason_code: string; status: string;
    stored_result_unchanged: boolean; provenance: string; report: string }[]
  id: string
  title: string
  state: string
  spec: JobSpec
  progress: number
  stage: string
  error: string
  created_at: string
  updated_at: string
  result?: {
    // Derived tasks (rejudge / resume) share the envelope but not the generate payload.
    kind?: 'rejudge' | 'resume'
    model_calls?: number
    parent_job_id?: string
    resumed_from?: string
    source_candidate_id?: string
    note?: string
    verdict?: { state: string; ac_status: string; total_testcases: number; total_correct: number
      runtime?: string; memory?: string; version?: string; cases_sha256?: string; correctness_order?: string }
    corpus?: { mode?: string; cases?: number; sha256?: string; validation_sha256?: string | null; package_sha256?: string | null }
    config?: { execution_path?: string; truncation?: boolean; version?: string }
    executor?: { path?: string; adapter_sha256?: string | null; receipt_sha256?: string | null; image?: string }
    first_failure?: { case: number; args: Record<string, unknown>; expected: unknown; note?: string }
    source_generations?: { qid: number; language: string; model_id: string; model_name: string; candidate: Candidate }[]
    groups?: ResultGroup[]
    notice?: string
    timing?: { wall_ms?: number; max_sandbox_concurrency: number; phases_ms: Record<string, number> }
    failure?: { phase: string; code: string; message: string; suggestion: string; retryable: boolean; attempt_count: number;
      context: { qid?: number; model_name?: string; language?: string; candidate_index?: number; probe_index?: number } }
    inputs?: { qid: number; probes: Record<string, unknown>[]; probe_sha256: string; validation_count: number; selection?: ProbeSelection }[]
    cross_language: { qid: number; model_id: string; left: string; right: string; agreement: number }[]
    testcase_workflow?: { state: string; target_per_question: number; events: { qid: number; stage: string; generated_count?: number }[];
      questions: { qid: number; state: string; generated_count: number; leetcode_alignment: string; requested_target?: number; effective_target?: number }[] }
  }
}
export interface CatalogProblem {
  lab_evidence?: { evidence_level: string; case_count: number; generated_count: number; package_sha256: string;
    reference_languages: string[]; execution_protocol?: { version: string; clock: string | null } | null; limitations: string[] }
  generation_available?: boolean
  generation_languages?: string[]
  problem_kind?: 'algorithm' | 'database' | 'dataframe' | 'shell'
  correctness_evidence?: CorrectnessEvidence
  qid: number; title: string; difficulty: string; corpus_cases: number; tags: string[]
  scope: 'ft100' | 'extension' | 'pending'
  evidence_level: string; available_languages: string[]; ready: boolean
  generated_cases: number; test_generation_available: boolean; test_generation_reason: string
}
export interface CorrectnessEvidence {
  state: 'not_audited' | 'verified' | 'gaps_found'
  profile_version: string
  case_count: number
  cases_sha256: string
  promoted?: boolean
  report_sha256?: string
  reference_gate_count?: number
  answer_checks?: { oracle_checked: number; outside_oracle_scope: number }
  mutation_summary?: { incorrect_total: number; verified_non_equivalent: number; killed: number; survived: number; pending: number; detection_rate: number | null; correct_total: number; correct_passed: number }
  scope?: { input_subset: string; answer_subset: string | null; oracle_limit: { parameter: string; max_length: number } | null; independent_oracle: string }
}
export interface Catalog {
  problems: CatalogProblem[]
  languages: { key: string; label: string }[]
  counts?: { total: number; ready: number; historical: number; extension: number; generated_ready: number; can_generate_tests: number; can_generate?: number; protocol_ready?: number; independent_package_ready?: number }
  warning?: string
}

export interface GeneratedSource {
  job_id: string; job_title: string; candidate_id: string; candidate_index: number
  qid: number; language: string; model_id: string; model_name: string; code_sha256: string
}
