<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { getPassKDashboard, getStatsOverview } from '@/api'
import type { PassKDashboardResponse, PassKValues, StatsOverview, TranslationPairPassK } from '@/types'

use([CanvasRenderer, BarChart, HeatmapChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent])

type PassKKey = keyof PassKValues

const languageOrder = ['C', 'C++', 'C#', 'Java', 'JavaScript', 'Python3', 'Rust', 'Golang']
const kOptions: { label: string; value: PassKKey }[] = [
  { label: 'Pass@1', value: 'pass_at_1' },
  { label: 'Pass@2', value: 'pass_at_2' },
  { label: 'Pass@3', value: 'pass_at_3' },
  { label: 'Pass@4', value: 'pass_at_4' },
  { label: 'Pass@5', value: 'pass_at_5' },
]

const loading = ref(true)
const overview = ref<StatsOverview | null>(null)
const passk = ref<PassKDashboardResponse | null>(null)
const selectedK = ref<PassKKey>('pass_at_1')
const selectedGenerationModel = ref('')
const selectedTranslationModel = ref('')

function kLabel(key: PassKKey) {
  return kOptions.find((item) => item.value === key)?.label ?? key
}

function score(row: PassKValues, key: PassKKey) {
  return Number(row[key].toFixed(1))
}

function classForScore(value: number) {
  if (value >= 70) return 'high'
  if (value >= 35) return 'medium'
  if (value > 0) return 'low'
  return 'none'
}

const statCards = computed(() => {
  if (!overview.value) return []
  return [
    { label: 'Generation Benchmark', value: overview.value.generation_benchmark_problems.toLocaleString(), type: 'success' },
    { label: 'Translation Benchmark', value: overview.value.translation_benchmark_problems.toLocaleString(), type: 'warning' },
  ]
})

const generationBarOption = computed(() => {
  const rows = passk.value?.generation_models ?? []
  if (!rows.length) return null
  return {
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${value.toFixed(1)}%` },
    grid: { left: 64, right: 20, top: 24, bottom: 76 },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.model_name),
      axisLabel: { rotate: 18, fontSize: 11 },
    },
    yAxis: { type: 'value', max: 100, name: kLabel(selectedK.value), axisLabel: { formatter: '{value}%' } },
    series: [
      {
        type: 'bar',
        barMaxWidth: 42,
        data: rows.map((row) => score(row, selectedK.value)),
        itemStyle: { color: '#4f6ef7', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top', formatter: '{c}%', fontSize: 10 },
      },
    ],
  }
})

const generationLanguageRows = computed(() => {
  const rows = passk.value?.generation_languages ?? []
  return languageOrder.map((language) => rows.find((row) => row.model_name === selectedGenerationModel.value && row.language === language))
})

const generationLanguageMatrix = computed(() => {
  return languageOrder.map((language, index) => {
    const row = generationLanguageRows.value[index]
    return {
      language,
      values: kOptions.map((item) => (row ? score(row, item.value) : 0)),
    }
  })
})

const generationLanguageHeatmap = computed(() => {
  if (!selectedGenerationModel.value) return null
  const data: number[][] = []
  generationLanguageMatrix.value.forEach((row, yIndex) => {
    row.values.forEach((value, xIndex) => data.push([xIndex, yIndex, value]))
  })
  return {
    tooltip: { position: 'top', formatter: (params: any) => `${languageOrder[params.value[1]]} · ${kOptions[params.value[0]]?.label ?? ''}: ${params.value[2]}%` },
    grid: { left: 96, right: 20, top: 20, bottom: 64 },
    xAxis: { type: 'category', data: kOptions.map((item) => item.label), splitArea: { show: true } },
    yAxis: { type: 'category', data: languageOrder, splitArea: { show: true } },
    visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 8, inRange: { color: ['#fee2e2', '#fef3c7', '#d1fae5'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params: any) => `${params.value[2]}%`, fontSize: 10 } }],
  }
})

const translationRows = computed(() => {
  return (passk.value?.translation_pairs ?? []).filter((row) => row.model_name === selectedTranslationModel.value)
})

const translationLanguages = computed(() => {
  const set = new Set<string>()
  translationRows.value.forEach((row) => {
    set.add(row.src_lang)
    set.add(row.tgt_lang)
  })
  return languageOrder.filter((language) => set.has(language))
})

const translationMap = computed(() => {
  const map: Record<string, TranslationPairPassK> = {}
  translationRows.value.forEach((row) => {
    map[`${row.src_lang}@@${row.tgt_lang}`] = row
  })
  return map
})

const translationHeatmap = computed(() => {
  const languages = translationLanguages.value
  if (!selectedTranslationModel.value || !languages.length) return null
  const data: number[][] = []
  languages.forEach((src, yIndex) => {
    languages.forEach((tgt, xIndex) => {
      const row = translationMap.value[`${src}@@${tgt}`]
      if (src !== tgt) data.push([xIndex, yIndex, row ? score(row, selectedK.value) : 0])
    })
  })
  return {
    tooltip: { position: 'top', formatter: (params: any) => `${languages[params.value[1]]} → ${languages[params.value[0]]}: ${params.value[2]}%` },
    grid: { left: 96, right: 20, top: 20, bottom: 64 },
    xAxis: { type: 'category', data: languages, splitArea: { show: true } },
    yAxis: { type: 'category', data: languages, splitArea: { show: true } },
    visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 8, inRange: { color: ['#fee2e2', '#fef3c7', '#d1fae5'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params: any) => `${params.value[2]}%`, fontSize: 10 } }],
  }
})

watch(passk, (value) => {
  selectedGenerationModel.value = value?.generation_model_names?.[0] ?? ''
  selectedTranslationModel.value = value?.translation_model_names?.[0] ?? ''
})

onMounted(async () => {
  try {
    const [overviewRes, passkRes] = await Promise.all([getStatsOverview(), getPassKDashboard()])
    overview.value = overviewRes.data
    passk.value = passkRes.data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <div class="stat-grid">
      <div v-for="card in statCards" :key="card.label" class="stat-card">
        <div class="stat-icon" :class="card.type">{{ card.label.slice(0, 1) }}</div>
        <div>
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <div class="matrix-controls">
      <el-select v-model="selectedK" style="width: 140px">
        <el-option v-for="item in kOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
    </div>

    <div class="card">
      <div class="card-title">Generation Pass@k by Model</div>
      <v-chart v-if="generationBarOption" :option="generationBarOption" style="height: 380px" autoresize />
      <div v-else class="empty-state">No generation Pass@k data</div>
    </div>

    <div class="chart-grid dashboard-grid">
      <div class="card">
        <div class="panel-head">
          <div class="card-title">Generation Language Pass@k</div>
          <el-select v-model="selectedGenerationModel" filterable style="width: 260px">
            <el-option v-for="model in passk?.generation_model_names ?? []" :key="model" :label="model" :value="model" />
          </el-select>
        </div>
        <v-chart v-if="generationLanguageHeatmap" :option="generationLanguageHeatmap" style="height: 420px" autoresize />
        <div v-else class="empty-state">No generation language data</div>
      </div>

      <div class="card">
        <div class="panel-head">
          <div class="card-title">Translation Pair Pass@k</div>
          <el-select v-model="selectedTranslationModel" filterable style="width: 260px">
            <el-option v-for="model in passk?.translation_model_names ?? []" :key="model" :label="model" :value="model" />
          </el-select>
        </div>
        <v-chart v-if="translationHeatmap" :option="translationHeatmap" style="height: 420px" autoresize />
        <div v-else class="empty-state">No translation Pass@k data</div>
      </div>
    </div>

    <div class="card compact-matrix">
      <div class="card-title">{{ selectedGenerationModel }} · Generation Matrix</div>
      <table class="mini-matrix">
        <thead>
          <tr>
            <th>Language</th>
            <th v-for="item in kOptions" :key="item.value">{{ item.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in generationLanguageMatrix" :key="row.language">
            <td>{{ row.language }}</td>
            <td v-for="(value, index) in row.values" :key="index">
              <span class="pass-cell" :class="classForScore(value)">{{ value }}%</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.dashboard-grid {
  margin-top: 20px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.panel-head .card-title {
  margin-bottom: 0;
}

.compact-matrix {
  margin-top: 20px;
  overflow-x: auto;
}

.mini-matrix {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.mini-matrix th,
.mini-matrix td {
  border-bottom: 1px solid var(--border-color);
  padding: 10px 12px;
  text-align: center;
}

.mini-matrix th:first-child,
.mini-matrix td:first-child {
  text-align: left;
  font-weight: 700;
}
</style>
