import axios from 'axios'
import type {
    Problem,
    ProblemDetail,
    Submission,
    GenCode,
    Translation,
    StatsOverview,
    ModelStatsResponse,
    CompletionStatsResponse,
    PassKDashboardResponse,
} from '@/types'

const api = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
})

// ---- Problems ----

export function getProblems(params?: {
    page?: number
    page_size?: number
    search?: string
    require_submission?: boolean
    benchmark?: 'all' | 'generation' | 'translation'
}) {
    return api.get<{ data: Problem[]; total: number }>('/problems', { params })
}

export function getProblem(qid: string) {
    return api.get<ProblemDetail>(`/problems/${qid}`)
}

// ---- Submissions ----

export function getSubmissions(params?: {
    qid?: string
    model?: string
    language?: string
    source_type?: 'generation' | 'translation'
    src_lang?: string
    tgt_lang?: string
    status?: string
    page?: number
    page_size?: number
}) {
    return api.get<{ data: Submission[]; total: number }>('/submissions', { params })
}

// ---- GenCode & Translations ----

export function getGenCode(qid: string, params?: { model?: string; language?: string }) {
    return api.get<{ data: GenCode[] }>(`/gencode/${qid}`, { params })
}

export function getTranslations(
    qid: string,
    params?: { model?: string; src_lang?: string; tgt_lang?: string }
) {
    return api.get<{ data: Translation[] }>(`/translations/${qid}`, { params })
}

// ---- Stats ----

export function getStatsOverview() {
    return api.get<StatsOverview>('/stats/overview')
}

export function getModelStats(model: string) {
    return api.get<ModelStatsResponse>(`/stats/model/${model}`)
}

export function getCompletionStats() {
    return api.get<CompletionStatsResponse>('/stats/completion')
}

export function getPassKDashboard() {
    return api.get<PassKDashboardResponse>('/stats/passk')
}

// ---- Config ----

export function getModels() {
    return api.get<{ data: string[] }>('/config/models')
}

export default api
