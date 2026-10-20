import axios from 'axios'
import type {
    AgreementResponse,
    CompletionStatsResponse,
    CorpusFix,
    LocalResult,
    ModelStatsResponse,
    Paginated,
    Problem,
    ProblemDetail,
    Slot,
    StatsOverview,
} from '@/types'

const api = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
})

// ---- 总览 ----

export function getStatsOverview() {
    return api.get<StatsOverview>('/stats/overview')
}

/** 一致性分析：本地判 vs LeetCode 判 —— 本仪表盘的核心 */
export function getAgreement(params?: { task?: 'gen' | 'trans' }) {
    return api.get<AgreementResponse>('/stats/agreement', { params })
}

export function getModelStats(model: string) {
    return api.get<ModelStatsResponse>(`/stats/model/${model}`)
}

export function getCompletionStats() {
    return api.get<CompletionStatsResponse>('/stats/completion')
}

// ---- 明细 ----

export function getSlots(params?: {
    qid?: string
    model?: string
    lang?: string
    task?: string
    klass?: string
    mismatches?: '1'
    page?: number
    page_size?: number
}) {
    return api.get<Paginated<Slot>>('/slots', { params })
}

export function getProblems(params?: {
    q?: string
    ft_only?: '1'
    fixed_only?: '1'
    page?: number
    page_size?: number
}) {
    return api.get<Paginated<Problem>>('/problems', { params })
}

export function getProblem(qid: string | number, params?: { page: number; page_size: number }) {
    return api.get<ProblemDetail>(`/problems/${qid}`, { params })
}

export function getLocalResults(params?: {
    qid?: string
    lang?: string
    ac_status?: string
    page?: number
    page_size?: number
}) {
    return api.get<Paginated<LocalResult>>('/local_results', { params })
}

export function getFixes() {
    return api.get<{ data: CorpusFix[] }>('/fixes')
}

// ---- 配置 ----

export function getModels() {
    return api.get<{ models: string[] }>('/config/models')
}

export default api
