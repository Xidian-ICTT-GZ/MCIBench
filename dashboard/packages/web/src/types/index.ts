// ===== Backend Data Models =====

export interface Problem {
    qid: string
    tid: string
    title: string
    slug: string
    url: string
    description: string
    difficulty: string
    is_benchmark: boolean
    is_generation_benchmark: boolean
    is_translation_benchmark: boolean
}

export interface Submission {
    id: number
    qid: string
    model_name: string
    language: string
    src_lang: string
    tgt_lang: string
    attempt_num: number
    submit_id: number
    ac_status: string
    runtime: string
    memory: string
    source_type: 'generation' | 'translation'
}

export interface GenCode {
    id: number
    qid: string
    model_name: string
    language: string
    attempt_num: number
    code: string
}

export interface Translation {
    id: number
    qid: string
    model_name: string
    src_lang: string
    tgt_lang: string
    attempt_num: number
    code: string
}

export interface Snippet {
    id: number
    qid: string
    language: string
    code: string
}

export interface Reference {
    id: number
    qid: string
    language: string
    attempt_num: number
    code: string
}

// ===== API Response Types =====

export interface ModelStat {
    model_name: string
    total: number
    accepted: number
    ac_rate: number
}

export interface LangStat {
    language: string
    total: number
    accepted: number
    ac_rate: number
}

export interface StatsOverview {
    problems: number
    generation_benchmark_problems: number
    translation_benchmark_problems: number
    submissions: number
    gen_codes: number
    translations: number
    models: ModelStat[]
    languages: string[]
}

export interface ModelStatsResponse {
    model_name: string
    total: number
    accepted: number
    ac_rate: number
    languages: LangStat[]
}

export interface CompletionRow {
    model_name: string
    language: string
    completed: number
    completion_rate: number
}

export interface CompletionStatsResponse {
    benchmark_total: number
    models: string[]
    languages: string[]
    rows: CompletionRow[]
}

export interface PassKValues {
    pass_at_1: number
    pass_at_2: number
    pass_at_3: number
    pass_at_4: number
    pass_at_5: number
}

export interface GenerationModelPassK extends PassKValues {
    model_name: string
}

export interface GenerationLanguagePassK extends PassKValues {
    model_name: string
    language: string
}

export interface TranslationPairPassK extends PassKValues {
    model_name: string
    src_lang: string
    tgt_lang: string
}

export interface PassKDashboardResponse {
    generation_models: GenerationModelPassK[]
    generation_languages: GenerationLanguagePassK[]
    translation_pairs: TranslationPairPassK[]
    generation_model_names: string[]
    translation_model_names: string[]
}

export interface PaginatedResponse<T> {
    data: T[]
    total: number
    page: number
    page_size: number
}

export interface ProblemDetail extends Problem {
    snippets: Snippet[]
    references: Reference[]
}
