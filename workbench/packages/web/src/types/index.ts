// ===== 本地判题仪表盘的数据模型 =====
//
// 与主仪表盘的关键差异：这里的主对象不是「一次 LeetCode 提交」，而是
// **一个配对槽位**（本地判一次 + LeetCode 判一次），核心字段是 klass ——
// 两者判定是否一致。整个仪表盘围绕这个分类展开。

/** 「本地判 vs LeetCode 判」的分类，口径与 local/audit/report.py 一致。
 *  `pending` 是本地盘特有的：主库有 LeetCode 判定但本地还没判过这个槽位。
 *  `no_lc` 相反：本地判过，但 LeetCode 侧没有判定记录 —— 无对照，
 *  不参与一致性统计（此前被算成 false_ac，等于把"不知道"当成"不过"）。 */
export type Klass = 'agrees' | 'same_neg' | 'false_ac' | 'false_wa'
    | 'no_corpus' | 'no_lc' | 'pending'

import { localizedLabels } from '@/i18n'

export const KLASS_LABEL = localizedLabels({
    agrees: '一致',
    same_neg: '双方都不过',
    false_ac: '本地过 / LC 不过',
    false_wa: '本地不过 / LC 过',
    no_corpus: '无本地语料',
    no_lc: '无 LC 判定',
    pending: '待本地判定',
})

export const KLASS_DOC = localizedLabels({
    agrees: '本地与 LeetCode 判定一致',
    same_neg: '双方都判不通过（类型可能不同；多为环境/编译差异）',
    false_ac: '本地 AC、LeetCode 非 AC —— 本地用例太弱（覆盖不足）',
    false_wa: '本地非 AC、LeetCode AC —— 本地用例太严，或判题器有缺陷',
    no_corpus: '该题不在本地评测集内，无法对拍',
    no_lc: 'LeetCode 侧没有判定记录 —— 无对照，不参与一致性统计',
    pending: '有 LeetCode 判定，但本地还没判过 —— 跑 judge_all_models 即可补上',
})

/** Element Plus 的 tag 颜色 */
export const KLASS_TAG: Record<Klass, string> = {
    agrees: 'success',
    same_neg: 'info',
    false_ac: 'danger',
    false_wa: 'warning',
    no_corpus: '',
    no_lc: '',
    pending: '',
}

export interface Problem {
    qid: number
    title: string
    slug: string
    difficulty: string
    url: string
    is_benchmark: number
    is_generation_benchmark: number
    is_translation_benchmark: number
    corpus_cases: number
    in_ft_test: number
}

export interface Run {
    run: string
    model: string
    task: string
    source_type: string
    slots: number
    local_ac: number
    leetcode_ac: number
}

export interface Slot {
    id: number
    run: string
    model: string
    task: string
    source_type: string
    qid: number
    lang: string
    src_lang: string
    tgt_lang: string
    cand: number
    leetcode: string
    local: string
    klass: Klass
    has_corpus: number
}

export interface LocalResult {
    id: number
    run_name: string
    model: string
    task: string
    qid: number
    lang: string
    src_lang: string
    tgt_lang: string
    cand: number
    state: string
    ac_status: string
    total_testcases: number
    total_correct: number
    runtime: string
    memory: string
}

export interface CorpusFix {
    qid: number
    title: string
    corpus_cases: number
    kind: string
    note: string
}

// ===== 接口响应 =====

export interface KlassCount {
    klass: Klass
    count: number
    doc: string
}

export interface ExcludedModel {
    model: string
    reason: string
}

// C-002：后端 `metrics` / `metrics_dev` / `metrics_holdout` 三块此前**没有任何
// 前端类型**，也就没有任何页面读它 —— 交接文档却写"仪表盘 overview 接口的
// metrics 三块就是这些数字"。于是总览 KPI 用一套分母、文档引用另一套，
// 读者无法对账。补上类型并把它们接到页面上。
export interface MetricsBlock {
    comparable_slots: number
    agrees: number
    same_neg: number
    false_ac: number
    false_wa: number
    no_lc: number
    tp: number
    fn: number
    fp: number
    tn: number
    exact_agree_rate: number
    binary_agree_rate: number
    miss_rate: number
    false_reject_rate: number
    /** 本地拒绝中 LC 接受的比例；规范 7.3 要求不得与漏检/误拒混名 */
    rejected_but_lc_accepted_rate: number
    /** 分母为 0 时前端应显示"不适用"而不是 0.0%（C-011） */
    miss_rate_applicable: boolean
    false_reject_rate_applicable: boolean
}

export interface StatsOverview {
    coverage?: { planned: number; current: number; stale: number; unverifiable: number; missing: number }
    problems: number
    ft_test_problems: number
    slots: number
    comparable_slots: number
    agreeing_slots: number
    agree_rate: number
    pending_slots: number
    runs: number
    local_results: number
    corpus_fixes: number
    klass: KlassCount[]
    models: string[]
    languages: string[]
    scope: string
    excluded_models: ExcludedModel[]
    metrics?: MetricsBlock
    metrics_dev?: MetricsBlock
    metrics_holdout?: MetricsBlock
}

export interface ModelAgreement {
    model_name: string
    total: number
    local_ac: number
    leetcode_ac: number
    agrees: number
    false_ac: number
    false_wa: number
    agree_rate: number
}

export interface LangAgreement {
    lang: string
    total: number
    agrees: number
    false_ac: number
    false_wa: number
}

export interface ProblemAgreement {
    qid: number
    title: string
    corpus_cases: number
    total: number
    agrees: number
    false_ac: number
    false_wa: number
    fixed: string
}

export interface AgreementResponse {
    by_model: ModelAgreement[]
    by_lang: LangAgreement[]
    by_problem: ProblemAgreement[]
}

export interface LangStat {
    language: string
    total: number
    agrees: number
    false_ac: number
    false_wa: number
    local_ac: number
    leetcode_ac: number
    agree_rate: number
}

export interface ModelStatsResponse {
    model_name: string
    total: number
    agrees: number
    agree_rate: number
    languages: LangStat[]
}

export interface CompletionRow {
    model_name: string
    language: string
    completed: number
}

export interface CompletionStatsResponse {
    benchmark_total: number
    rows: CompletionRow[]
    note: string
}

export interface Paginated<T> {
    data: T[]
    total: number
    page: number
    page_size: number
}

export interface ProblemDetail {
    total: number
    page: number
    page_size: number
    metrics: MetricsBlock
    problem: Problem
    fixes: CorpusFix[]
    slots: Pick<Slot, 'model' | 'lang' | 'task' | 'cand' | 'leetcode' | 'local' | 'klass'>[]
}
