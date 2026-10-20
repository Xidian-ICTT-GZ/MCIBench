<script setup lang="ts">
import { t, problemTitle } from '@/i18n'

import { onMounted, ref } from 'vue'
import { getAgreement } from '@/api'
import type { AgreementResponse } from '@/types'
import { KLASS_TAG, type Klass } from '@/types'

const loading = ref(true)
const err = ref('')
const ag = ref<AgreementResponse | null>(null)
const task = ref<'' | 'gen' | 'trans'>('')
const onlyDiff = ref(false)

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await getAgreement(task.value ? { task: task.value } : undefined)
    ag.value = r.data
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`
}

function rateTag(v: number) {
  return v >= 0.97 ? 'success' : v >= 0.9 ? 'warning' : 'danger'
}

function diffCount(p: { false_ac: number; false_wa: number }) {
  return p.false_ac + p.false_wa
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon />

    <el-card shadow="never" style="margin-bottom: 14px;">
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <span style="font-weight:600">{{ t("任务") }}</span>
        <el-radio-group v-model="task" @change="load">
          <el-radio-button label="">{{ t("全部") }}</el-radio-button>
          <el-radio-button label="gen">{{ t("代码生成") }}</el-radio-button>
          <el-radio-button label="trans">{{ t("代码翻译") }}</el-radio-button>
        </el-radio-group>
        <el-checkbox v-model="onlyDiff" style="margin-left:8px">{{ t("只看有差异的题目") }}</el-checkbox>
        <span style="font-size:12px;opacity:.6">
          {{ t("一致率＝本地与 LeetCode 判定相同的槽位占比。本地过/LC不过＝语料太弱；本地不过/LC过＝语料太严或判题器有缺陷。") }}
        </span>
      </div>
    </el-card>

    <template v-if="ag">
      <!-- 按模型 -->
      <el-card shadow="never" style="margin-bottom: 14px;">
        <template #header><span style="font-weight:600">{{ t("按模型") }}</span></template>
        <el-table :data="ag.by_model" size="small" border>
          <el-table-column prop="model_name" :label='t("模型")' width="150" />
          <el-table-column prop="total" :label='t("槽位")' width="100" align="right" />
          <el-table-column prop="agrees" :label='t("一致")' width="100" align="right" />
          <el-table-column :label='t("一致率")' width="110" align="right">
            <template #default="{ row }">
              <el-tag :type="rateTag(row.agree_rate)" size="small" effect="plain">
                {{ pct(row.agree_rate) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="local_ac" :label='t("本地 AC")' width="110" align="right" />
          <el-table-column prop="leetcode_ac" label="LC AC" width="110" align="right" />
          <el-table-column :label='t("本地过/LC不过")' width="150" align="right">
            <template #default="{ row }">
              <span :style="{ color: row.false_ac ? '#f56c6c' : 'inherit', fontWeight: row.false_ac ? 600 : 400 }">
                {{ row.false_ac }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label='t("本地不过/LC过")' width="150" align="right">
            <template #default="{ row }">
              <span :style="{ color: row.false_wa ? '#e6a23c' : 'inherit', fontWeight: row.false_wa ? 600 : 400 }">
                {{ row.false_wa }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 按语言 -->
      <el-card shadow="never" style="margin-bottom: 14px;">
        <template #header><span style="font-weight:600">{{ t("按语言") }}</span></template>
        <el-table :data="ag.by_lang" size="small" border>
          <el-table-column prop="lang" :label='t("语言")' width="140" />
          <el-table-column prop="total" :label='t("槽位")' width="110" align="right" />
          <el-table-column prop="agrees" :label='t("一致")' width="110" align="right" />
          <el-table-column prop="false_ac" :label='t("本地过/LC不过")' width="150" align="right" />
          <el-table-column prop="false_wa" :label='t("本地不过/LC过")' width="150" align="right" />
          <el-table-column :label='t("差异占比")' align="right">
            <template #default="{ row }">
              {{ row.total ? ((row.false_ac + row.false_wa) / row.total * 100).toFixed(1) + '%' : '-' }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 按题目 -->
      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600">{{ t("按题目") }}</span>
          <span style="font-size:12px;opacity:.6;margin-left:8px">
            {{ t("按差异槽位数降序；「已修」是本次工作对该题语料的修复记录") }}
          </span>
        </template>
        <el-table :data="ag.by_problem.filter(p => !onlyDiff || diffCount(p) > 0)" size="small" border height="520">
          <el-table-column :label='t("题号")' width="90" fixed>
            <template #default="{ row }">
              <router-link :to="`/problems/${row.qid}`" style="color:#409eff">q{{ row.qid }}</router-link>
            </template>
          </el-table-column>
          <el-table-column prop="title" :label='t("标题")' width="230" ><template #default="{ row }">{{ problemTitle(row) }}</template></el-table-column>
          <el-table-column prop="corpus_cases" :label='t("语料")' width="70" align="right" />
          <el-table-column prop="total" :label='t("槽位")' width="80" align="right" />
          <el-table-column :label='t("本地过/LC不过")' width="140" align="right" sortable :sort-method="(a: any, b: any) => a.false_ac - b.false_ac">
            <template #default="{ row }">
              <span :style="{ color: row.false_ac ? '#f56c6c' : 'inherit', fontWeight: row.false_ac ? 600 : 400 }">
                {{ row.false_ac }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label='t("本地不过/LC过")' width="140" align="right" sortable :sort-method="(a: any, b: any) => a.false_wa - b.false_wa">
            <template #default="{ row }">
              <span :style="{ color: row.false_wa ? '#e6a23c' : 'inherit', fontWeight: row.false_wa ? 600 : 400 }">
                {{ row.false_wa }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label='t("已修")' min-width="260">
            <template #default="{ row }">
              <span v-if="row.fixed" style="font-size:12px">{{ t(row.fixed) }}</span>
              <span v-else style="opacity:.35;font-size:12px">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>
