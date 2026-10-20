<script setup lang="ts">
import { t, problemTitle } from '@/i18n'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getProblem } from '@/api'
import type { ProblemDetail } from '@/types'
import { KLASS_LABEL, KLASS_TAG, type Klass } from '@/types'

const route = useRoute()
const qid = computed(() => String(route.params.qid || ''))

const loading = ref(true)
const err = ref('')
const detail = ref<ProblemDetail | null>(null)
const modelFilter = ref('')
const langFilter = ref('')
const onlyDiff = ref(false)
const page = ref(1)
const pageSize = 100

function statusType(s: string) {
  if (s === 'Accepted') return 'success'
  if (s === 'Wrong Answer') return 'danger'
  if (s === 'Compile Error') return 'info'
  return 'warning'
}

const models = computed(() =>
  Array.from(new Set((detail.value?.slots || []).map((s) => s.model))).sort())
const langs = computed(() =>
  Array.from(new Set((detail.value?.slots || []).map((s) => s.lang))).filter(Boolean).sort())

const filtered = computed(() => {
  let rows = detail.value?.slots || []
  if (modelFilter.value) rows = rows.filter((r) => r.model === modelFilter.value)
  if (langFilter.value) rows = rows.filter((r) => r.lang === langFilter.value)
  if (onlyDiff.value) rows = rows.filter((r) => r.klass === 'false_ac' || r.klass === 'false_wa')
  return rows
})

const summary = computed(() => ({
  false_ac: detail.value?.metrics.false_ac || 0,
  false_wa: detail.value?.metrics.false_wa || 0,
}))

async function load() {
  loading.value = true
  err.value = ''
  try {
    detail.value = (await getProblem(qid.value, { page: page.value, page_size: pageSize })).data
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(qid, () => { page.value = 1; load() })
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon
              style="margin-bottom:14px" />

    <template v-if="detail">
      <el-card shadow="never" style="margin-bottom: 14px;">
        <template #header>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <span style="font-weight:700;font-size:16px">q{{ detail.problem.qid }}</span>
            <span style="font-size:16px">{{ problemTitle(detail.problem) }}</span>
            <el-tag v-if="detail.problem.in_ft_test" type="success" size="small" effect="plain">{{ t("100 题评测集") }}</el-tag>
            <el-tag v-if="detail.problem.difficulty" size="small" effect="plain">{{ detail.problem.difficulty }}</el-tag>
            <a v-if="detail.problem.url" :href="detail.problem.url" target="_blank"
               style="color:#409eff;font-size:13px">LeetCode ↗</a>
            <router-link to="/problems" style="margin-left:auto;font-size:13px">{{ t("← 返回题目列表") }}</router-link>
          </div>
        </template>
        <el-row :gutter="14">
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="color:#409eff">{{ detail.problem.corpus_cases || '—' }}</div>
              <div class="kpi-l">{{ t("本地语料条数") }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n">{{ detail.metrics.comparable_slots }}</div>
              <div class="kpi-l">{{ t("可比槽位") }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="color:#f56c6c">{{ summary['false_ac'] || 0 }}</div>
              <div class="kpi-l">{{ t("本地过 / LC 不过") }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="color:#e6a23c">{{ summary['false_wa'] || 0 }}</div>
              <div class="kpi-l">{{ t("本地不过 / LC 过") }}</div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <el-card v-if="detail.fixes.length" shadow="never" style="margin-bottom: 14px;">
        <template #header><span style="font-weight:600">{{ t("本题的历史语料修复记录") }}</span></template>
        <el-table :data="detail.fixes" size="small" border>
          <el-table-column prop="kind" :label='t("类别")' width="170" ><template #default="{ row }">{{ t(row.kind) }}</template></el-table-column>
          <el-table-column prop="note" :label='t("历史修复内容与当时记录")' ><template #default="{ row }">{{ t(row.note) }}</template></el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600">{{ t("各模型 × 语言的判定") }}</span>
        </template>
        <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <el-select v-model="modelFilter" :placeholder='t("筛选本页模型")' style="width:150px" clearable>
            <el-option v-for="m in models" :key="m" :label="m" :value="m" />
          </el-select>
          <el-select v-model="langFilter" :placeholder='t("筛选本页语言")' style="width:130px" clearable>
            <el-option v-for="l in langs" :key="l" :label="l" :value="l" />
          </el-select>
          <el-checkbox v-model="onlyDiff">{{ t("本页只看判定不一致") }}</el-checkbox>
          <span style="font-size:12px;opacity:.6">{{ t("本页筛选后") }} {{ filtered.length }} {{ t("条 / 当前范围共") }} {{ detail.total }} {{ t("条") }}</span>
        </div>
        <el-table :data="filtered" size="small" border max-height="520">
          <el-table-column prop="model" :label='t("模型")' width="140" />
          <el-table-column prop="lang" :label='t("语言")' width="120" />
          <el-table-column prop="task" :label='t("任务")' width="80" />
          <el-table-column prop="cand" :label='t("候选")' width="70" align="right" />
          <el-table-column label="LeetCode" width="160">
            <template #default="{ row }">
              <el-tag :type="statusType(row.leetcode)" size="small" effect="plain">{{ row.leetcode }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label='t("本地")' width="160">
            <template #default="{ row }">
              <el-tag :type="statusType(row.local)" size="small" effect="plain">{{ row.local }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label='t("分类")' min-width="170">
            <template #default="{ row }">
              <el-tag :type="(KLASS_TAG[row.klass as Klass] as any) || 'info'" size="small">
                {{ KLASS_LABEL[row.klass as Klass] || row.klass }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="detail.total"
          layout="total, prev, pager, next" @current-change="load" style="margin-top:12px" />
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.kpi { text-align: center; padding: 6px 0; }
.kpi-n { font-size: 24px; font-weight: 700; line-height: 1.3; }
.kpi-l { font-size: 12px; opacity: .65; margin-top: 2px; }
</style>
