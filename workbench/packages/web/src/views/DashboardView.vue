<script setup lang="ts">
import { t, problemTitle } from '@/i18n'

import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { locale } from '@/i18n'
import * as echarts from 'echarts'
import { getAgreement, getFixes, getStatsOverview } from '@/api'
import type { AgreementResponse, CorpusFix, StatsOverview } from '@/types'
import { KLASS_LABEL, KLASS_DOC, KLASS_TAG, type Klass } from '@/types'

const loading = ref(true)
const err = ref('')
const ov = ref<StatsOverview | null>(null)
const ag = ref<AgreementResponse | null>(null)
const fixes = ref<CorpusFix[]>([])

const pieEl = ref<HTMLDivElement>()
const barEl = ref<HTMLDivElement>()

const KLASS_COLOR: Record<string, string> = {
  agrees: '#67c23a',
  false_ac: '#f56c6c',
  false_wa: '#e6a23c',
  same_neg: '#909399',
  pending: '#c0c4cc',
}

function drawPie() {
  if (!pieEl.value || !ov.value) return
  const ch = echarts.getInstanceByDom(pieEl.value) || echarts.init(pieEl.value)
  const rows = ov.value.klass.filter((k) => k.klass !== 'no_corpus')
  ch.setOption({
    tooltip: { trigger: 'item', formatter: t("{b}<br/>{c} 个槽位 ({d}%)") },
    legend: { type: 'scroll', bottom: 0, width: '90%', textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      center: ['50%', '43%'],
      radius: ['36%', '60%'],
      label: { formatter: '{b}\n{c}', fontSize: 11, width: 95, overflow: 'truncate' },
      data: rows.map((k) => ({
        name: KLASS_LABEL[k.klass as Klass] || k.klass,
        value: k.count,
        itemStyle: { color: KLASS_COLOR[k.klass] || '#409eff' },
      })),
    }],
  })
}

function drawBar() {
  if (!barEl.value || !ag.value) return
  const top = ag.value.by_problem.slice(0, 12)
  const ch = echarts.getInstanceByDom(barEl.value) || echarts.init(barEl.value)
  ch.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { type: 'scroll', bottom: 0, width: '90%', textStyle: { fontSize: 11 } },
    grid: { left: 52, right: 20, top: 20, bottom: 58 },
    xAxis: {
      type: 'category',
      data: top.map((p) => `q${p.qid}`),
      axisLabel: { fontSize: 10, rotate: 40 },
    },
    yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
    series: [
      { name: t("本地过/LC不过"), type: 'bar', stack: 'a', data: top.map((p) => p.false_ac), itemStyle: { color: '#f56c6c' } },
      { name: t("本地不过/LC过"), type: 'bar', stack: 'a', data: top.map((p) => p.false_wa), itemStyle: { color: '#e6a23c' } },
    ],
  })
}

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`
}

watch(locale, async () => { await nextTick(); drawPie(); drawBar() })
onBeforeUnmount(() => {
  if (pieEl.value) echarts.getInstanceByDom(pieEl.value)?.dispose()
  if (barEl.value) echarts.getInstanceByDom(barEl.value)?.dispose()
})

onMounted(async () => {
  try {
    const [o, a, f] = await Promise.all([getStatsOverview(), getAgreement(), getFixes()])
    ov.value = o.data
    ag.value = a.data
    fixes.value = f.data.data
    loading.value = false
    setTimeout(() => { drawPie(); drawBar() }, 60)
  } catch (e: any) {
    err.value = e?.message || String(e)
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon />

    <template v-if="ov">
      <el-alert v-if="ov.coverage" type="info" :closable="false" style="margin-bottom:14px">
        <template #title>{{ t("当前版本有效结果") }} {{ ov.coverage.current }} / {{ ov.coverage.planned }} {{ t("个计划槽位") }}</template>
        {{ t("过期") }} {{ ov.coverage.stale }}{{ t("，无法验证") }} {{ ov.coverage.unverifiable }}{{ t("，缺失") }} {{ ov.coverage.missing }}{{ t("。 下方一致率仅使用身份有效、双方有判定的结果；有效覆盖不足时不能代表完整评测表现。") }}
      </el-alert>
      <el-row :gutter="10" style="margin-bottom: 14px;">
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n">{{ ov.ft_test_problems }}</div>
            <div class="kpi-l">{{ t("评测集题目") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n">{{ ov.models.length }}</div>
            <div class="kpi-l">
              {{ t("有效结果覆盖模型") }}<span v-if="ov.excluded_models?.length"
                       style="color:#e6a23c">{{ t("（另排除") }} {{ ov.excluded_models.length }}）</span>
            </div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n">{{ ov.comparable_slots.toLocaleString() }}</div>
            <div class="kpi-l">{{ t("可比对槽位") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#67c23a">{{ ov.comparable_slots > 0 ? pct(ov.agree_rate) : t("不适用") }}</div>
            <div class="kpi-l">{{ t("判定一致率") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#f56c6c">
              {{ (ov.klass.find(k => k.klass === 'false_ac')?.count || 0).toLocaleString() }}
            </div>
            <div class="kpi-l">{{ t("本地过 / LC 不过") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#e6a23c">
              {{ (ov.klass.find(k => k.klass === 'false_wa')?.count || 0).toLocaleString() }}
            </div>
            <div class="kpi-l">{{ t("本地不过 / LC 过") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#c0c4cc">{{ (ov.pending_slots || 0).toLocaleString() }}</div>
            <div class="kpi-l">{{ t("待本地判定") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="3">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#409eff">{{ ov.corpus_fixes }}</div>
            <div class="kpi-l">{{ t("历史修复记录数") }}</div>
          </div></el-card>
        </el-col>
      </el-row>

      <!-- C-002：把后端 `metrics` 块接到页面上。
           此前前端**一个 metrics 字段都没读**，总览 KPI 用的是另一套分母
           （含 no_lc 的 7168），而交接文档引用的是 metrics 的 7148 ——
           两个数都叫"一致率"，读者无法对账。
           这里显式列出 2×2 与三个方向性指标，并**标出分子/分母**。 -->
      <el-card v-if="ov.metrics" shadow="never" style="margin-bottom:14px">
        <template #header>
          <span style="font-weight:600">{{ t("指标明细（规范 7.3 口径）") }}</span>
          <span style="font-size:12px;opacity:.65;margin-left:8px">
            {{ t("分母 = 可比槽位") }} {{ ov.metrics.comparable_slots.toLocaleString() }}
            {{ t("（已剔除") }} {{ ov.metrics.no_lc }} {{ t("个 LC 无判定的槽位）") }}
          </span>
        </template>
        <el-row :gutter="12">
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n">{{ ov.metrics.comparable_slots > 0 ? pct(ov.metrics.exact_agree_rate) : t("不适用") }}</div>
              <div class="kpi-l">
                {{ t("精确一致 = agrees/N =") }} {{ ov.metrics.agrees.toLocaleString() }}/{{
                  ov.metrics.comparable_slots.toLocaleString() }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n">{{ ov.metrics.comparable_slots > 0 ? pct(ov.metrics.binary_agree_rate) : t("不适用") }}</div>
              <div class="kpi-l">
                {{ t("二元一致 = (TP+TN)/N =") }} {{ (ov.metrics.tp + ov.metrics.tn).toLocaleString() }}/{{
                  ov.metrics.comparable_slots.toLocaleString() }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <!-- C-011：分母为 0 时显示"不适用"，不要渲染成 0.0% -->
              <div class="kpi-n" style="color:#f56c6c">
                {{ ov.metrics.miss_rate_applicable ? pct(ov.metrics.miss_rate) : t("不适用") }}
              </div>
              <div class="kpi-l">
                {{ t("漏检率 = FP/(FP+TN) =") }} {{ ov.metrics.fp }}/{{
                  ov.metrics.fp + ov.metrics.tn }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="color:#e6a23c">
                {{ ov.metrics.false_reject_rate_applicable
                   ? pct(ov.metrics.false_reject_rate) : t("不适用") }}
              </div>
              <div class="kpi-l">
                {{ t("误拒率 = FN/(TP+FN) =") }} {{ ov.metrics.fn }}/{{
                  ov.metrics.tp + ov.metrics.fn }}
              </div>
            </div>
          </el-col>
        </el-row>
        <el-row :gutter="12" style="margin-top:12px">
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="font-size:18px">
                TP {{ ov.metrics.tp.toLocaleString() }} ·
                FN {{ ov.metrics.fn.toLocaleString() }}
              </div>
              <div class="kpi-l">{{ t("LC 接受：本地也接受 / 本地拒绝") }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="font-size:18px">
                FP {{ ov.metrics.fp.toLocaleString() }} ·
                TN {{ ov.metrics.tn.toLocaleString() }}
              </div>
              <div class="kpi-l">{{ t("LC 拒绝：本地接受 / 本地也拒绝") }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="font-size:18px">
                {{ ov.metrics.fn + ov.metrics.tn > 0 ? pct(ov.metrics.rejected_but_lc_accepted_rate) : t("不适用") }}
              </div>
              <div class="kpi-l">
                {{ t("本地拒绝中 LC 接受 = FN/(FN+TN)（**不是**误拒率）") }}
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="kpi">
              <div class="kpi-n" style="font-size:18px">
                {{ ov.metrics.same_neg.toLocaleString() }}
              </div>
              <div class="kpi-l">
                {{ t("双方都不过（same_neg）—— **不等于** TN；TN 还含 agrees 里 双方同类型失败的槽位") }}
              </div>
            </div>
          </el-col>
        </el-row>
        <div v-if="ov.metrics_dev && ov.metrics_holdout"
             style="margin-top:12px;padding-top:10px;border-top:1px dashed #ebeef5;
                    font-size:12px;line-height:1.8;opacity:.85">
          <b>{{ t("开发集 / 留出集") }}</b>{{ t("（**只能做描述性比较**，不能当作无偏验证 —— 划分是按语料修改历史事后反推的，且 q922/q2610/q1304 的 checker 都是被它们自身在 holdout 里的失败驱动的）：") }}
          <div>
            {{ t("dev：可比") }} {{ ov.metrics_dev.comparable_slots.toLocaleString() }}{{ t("， 精确") }} {{ ov.metrics_dev.comparable_slots > 0 ? pct(ov.metrics_dev.exact_agree_rate) : t("不适用") }}，
            {{ ov.metrics_dev.miss_rate_applicable
               ? t("漏检") + ' ' + pct(ov.metrics_dev.miss_rate) : t("漏检 不适用") }}，
            {{ ov.metrics_dev.false_reject_rate_applicable
               ? t("误拒") + ' ' + pct(ov.metrics_dev.false_reject_rate) : t("误拒 不适用") }}
          </div>
          <div>
            {{ t("holdout：可比") }} {{ ov.metrics_holdout.comparable_slots.toLocaleString() }}{{ t("， 精确") }} {{ ov.metrics_holdout.comparable_slots > 0 ? pct(ov.metrics_holdout.exact_agree_rate) : t("不适用") }}，
            {{ ov.metrics_holdout.miss_rate_applicable
               ? t("漏检") + ' ' + pct(ov.metrics_holdout.miss_rate) : t("漏检 不适用") }}，
            {{ ov.metrics_holdout.false_reject_rate_applicable
               ? t("误拒") + ' ' + pct(ov.metrics_holdout.false_reject_rate) : t("误拒 不适用") }}
          </div>
        </div>
      </el-card>

      <el-card v-if="ov.excluded_models && ov.excluded_models.length" shadow="never"
               style="margin-bottom: 14px; border-left: 3px solid #e6a23c;">
        <template #header>
          <span style="font-weight:600">{{ t("已排除") }} {{ ov.excluded_models.length }} {{ t("个模型") }}</span>
          <span style="font-size:12px;opacity:.65;margin-left:8px">
            {{ t("原始判题结果仍保留在 local/results/all_models/ 下，此处只是不计入统计") }}
          </span>
        </template>
        <div v-for="e in ov.excluded_models" :key="e.model"
             style="padding:8px 0;border-bottom:1px dashed #ebeef5;">
          <b style="color:#e6a23c">{{ e.model }}</b>
          <div style="font-size:12px;line-height:1.7;opacity:.8;margin-top:3px">{{ t(e.reason) }}</div>
        </div>
      </el-card>

      <el-card shadow="never" style="margin-bottom: 14px;">
        <template #header>
          <span style="font-weight:600">{{ t("分类口径") }}</span>
          <el-tag size="small" type="info" effect="plain" style="margin-left:8px">
            {{ t("共") }} {{ ov.slots.toLocaleString() }} {{ t("个槽位，其中") }} {{ ov.comparable_slots.toLocaleString() }} {{ t("个可比对") }}
          </el-tag>
        </template>
        <el-table :data="ov.klass" size="small" border>
          <el-table-column :label='t("分类")' width="160">
            <template #default="{ row }">
              <el-tag :type="(KLASS_TAG[row.klass as Klass] as any) || 'info'" effect="plain">
                {{ KLASS_LABEL[row.klass as Klass] || row.klass }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="klass" :label='t("内部值")' width="120" />
          <el-table-column prop="count" :label='t("槽位数")' width="110" align="right" />
          <el-table-column :label='t("含义")'><template #default="{ row }">{{ KLASS_DOC[row.klass] || t(row.doc) }}</template></el-table-column>
        </el-table>
      </el-card>

      <el-row :gutter="14" style="margin-bottom: 14px;">
        <el-col :span="10">
          <el-card shadow="never">
            <template #header><span style="font-weight:600">{{ t("判定分类分布") }}</span></template>
            <div ref="pieEl" style="height: 300px;"></div>
          </el-card>
        </el-col>
        <el-col :span="14">
          <el-card shadow="never">
            <template #header>
              <span style="font-weight:600">{{ t("差异最多的题目") }}</span>
              <span style="font-size:12px;opacity:.6;margin-left:8px">{{ t("前 12 题，按差异槽位数") }}</span>
            </template>
            <div ref="barEl" style="height: 300px;"></div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600">{{ t("历史语料修复记录（") }}{{ fixes.length }} {{ t("条）") }}</span>
          <router-link to="/fixes" style="float:right;font-size:12px">{{ t("查看全部 →") }}</router-link>
        </template>
        <el-table :data="fixes.slice(0, 8)" size="small" border>
          <el-table-column :label='t("题号")' width="90">
            <template #default="{ row }">
              <router-link :to="`/problems/${row.qid}`" style="color:#409eff">q{{ row.qid }}</router-link>
            </template>
          </el-table-column>
          <el-table-column prop="title" :label='t("标题")' width="240" ><template #default="{ row }">{{ problemTitle(row) }}</template></el-table-column>
          <el-table-column prop="kind" :label='t("类别")' width="150" ><template #default="{ row }">{{ t(row.kind) }}</template></el-table-column>
          <el-table-column prop="corpus_cases" :label='t("语料")' width="70" align="right" />
          <el-table-column prop="note" :label='t("历史修复内容与当时记录")' ><template #default="{ row }">{{ t(row.note) }}</template></el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.kpi { text-align: center; padding: 4px 0; }
.kpi-n { font-size: 24px; font-weight: 700; line-height: 1.3; }
.kpi-l { font-size: 12px; opacity: .65; margin-top: 2px; }
</style>
