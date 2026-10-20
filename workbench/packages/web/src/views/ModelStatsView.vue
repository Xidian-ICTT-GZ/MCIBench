<script setup lang="ts">
import { t } from '@/i18n'

import { onMounted, ref } from 'vue'
import { getModelStats, getModels } from '@/api'
import type { ModelStatsResponse } from '@/types'

const loading = ref(false)
const err = ref('')
const models = ref<string[]>([])
const current = ref('')
const stat = ref<ModelStatsResponse | null>(null)

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`
}

async function load(m?: string) {
  if (!m) return
  current.value = m
  loading.value = true
  err.value = ''
  try {
    stat.value = (await getModelStats(m)).data
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const r = await getModels()
  models.value = r.data.models
  if (models.value.length) await load(models.value[0])
})
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon
              style="margin-bottom:14px" />

    <el-card shadow="never" style="margin-bottom: 14px;">
      <div style="display:flex;gap:10px;align-items:center">
        <span style="font-weight:600">{{ t("模型") }}</span>
        <el-radio-group :model-value="current" @change="(v: any) => load(v)">
          <el-radio-button v-for="m in models" :key="m" :label="m">{{ m }}</el-radio-button>
        </el-radio-group>
      </div>
    </el-card>

    <template v-if="stat">
      <el-row :gutter="14" style="margin-bottom: 14px;">
        <el-col :span="8">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n">{{ stat.total.toLocaleString() }}</div>
            <div class="kpi-l">{{ t("对拍槽位") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n" style="color:#67c23a">{{ stat.total > 0 ? pct(stat.agree_rate) : t("不适用") }}</div>
            <div class="kpi-l">{{ t("判定一致率") }}</div>
          </div></el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="never"><div class="kpi">
            <div class="kpi-n">{{ stat.agrees.toLocaleString() }}</div>
            <div class="kpi-l">{{ t("一致槽位") }}</div>
          </div></el-card>
        </el-col>
      </el-row>

      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600">{{ stat.model_name }} {{ t("· 分语言一致性") }}</span>
        </template>
        <el-table :data="stat.languages" size="small" border>
          <el-table-column prop="language" :label='t("语言")' width="140" />
          <el-table-column prop="total" :label='t("槽位")' width="110" align="right" />
          <el-table-column prop="agrees" :label='t("一致")' width="110" align="right" />
          <el-table-column :label='t("一致率")' width="120" align="right">
            <template #default="{ row }">
              <el-tag :type="row.agree_rate >= 0.97 ? 'success' : row.agree_rate >= 0.9 ? 'warning' : 'danger'"
                      size="small" effect="plain">{{ row.total > 0 ? pct(row.agree_rate) : t("不适用") }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="local_ac" :label='t("本地 AC")' width="110" align="right" />
          <el-table-column prop="leetcode_ac" label="LC AC" width="110" align="right" />
          <el-table-column prop="false_ac" :label='t("本地过/LC不过")' width="150" align="right" />
          <el-table-column prop="false_wa" :label='t("本地不过/LC过")' width="150" align="right" />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.kpi { text-align: center; padding: 4px 0; }
.kpi-n { font-size: 26px; font-weight: 700; line-height: 1.3; }
.kpi-l { font-size: 12px; opacity: .65; margin-top: 2px; }
</style>
