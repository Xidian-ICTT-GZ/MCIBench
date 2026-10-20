<script setup lang="ts">
import type { CorrectnessEvidence } from '@/types/lab'
import { t } from '@/i18n'
defineProps<{ evidence?: CorrectnessEvidence; compact?: boolean }>()
</script>

<template>
  <section class="correctness-evidence" :class="{ compact }">
    <el-tag size="small" :type="evidence?.state === 'verified' ? 'success' : 'info'" effect="plain">
      {{ evidence?.state === 'verified' ? t('功能回归已验证') : evidence?.state === 'gaps_found' ? t('功能回归存在缺口') : t('本轮功能回归未验证') }}
    </el-tag>
    <div v-if="evidence?.mutation_summary" class="evidence-line">
      {{ t('已知错误检出 {0}/{1} · 正确改写通过 {2}/{3}', [evidence.mutation_summary.killed, evidence.mutation_summary.incorrect_total, evidence.mutation_summary.correct_passed, evidence.mutation_summary.correct_total]) }}
    </div>
    <div v-if="!compact" class="evidence-line">
      {{ t('判定配置') }}: <code>{{ evidence?.profile_version || 'historical_saved_profile' }}</code>
      <span v-if="evidence"> · {{ evidence.case_count }} {{ t('个测试输入') }} · SHA {{ evidence.cases_sha256.slice(0,12) }}</span>
      <span v-if="evidence?.reference_gate_count"> · {{ t('参考语言门禁 {0}', [evidence.reference_gate_count]) }}</span>
    </div>
    <div v-if="evidence?.scope?.oracle_limit" class="evidence-line">
      {{ t('独立答案算法范围：{0} 长度不超过 {1}', [evidence.scope.oracle_limit.parameter, evidence.scope.oracle_limit.max_length]) }}
    </div>
    <div v-if="!compact && evidence?.scope" class="evidence-line">{{ t('答案依据：官方示例、独立算法及参考解门禁') }} · <code>{{ evidence.scope.independent_oracle }}</code></div>
    <div v-if="!compact && evidence?.answer_checks" class="evidence-line">{{ t('独立答案核验 {0} 条 · 算法范围外 {1} 条', [evidence.answer_checks.oracle_checked, evidence.answer_checks.outside_oracle_scope]) }}</div>
    <div v-if="!compact && evidence?.scope?.input_subset === 'printable_ascii'" class="evidence-line">{{ t('输入字符证据限于可打印 ASCII 子集') }}</div>
    <div v-if="!compact && evidence?.scope?.answer_subset === 'signed_int32_answer'" class="evidence-line">{{ t('独立答案证据限于 int32 可表示结果') }}</div>
    <p v-if="!compact">{{ t('检出率只描述已审查错误程序，不是正确率；本地验证不保证 LeetCode 通过，也不证明选码策略有效。') }}</p>
    <p v-if="!compact && !evidence">{{ t('历史任务保留原判定版本，未追写本轮审计结论。') }}</p>
  </section>
</template>

<style scoped>
.correctness-evidence { padding:12px 14px; margin:12px 0; background:var(--bg-page); border:1px solid var(--border-color); border-radius:8px; font-size:12px; line-height:1.8; overflow-wrap:anywhere }
.correctness-evidence p,.evidence-line { color:var(--text-secondary) }
.correctness-evidence.compact { padding:6px 0; margin:4px 0 0; border:0; background:transparent }
</style>
