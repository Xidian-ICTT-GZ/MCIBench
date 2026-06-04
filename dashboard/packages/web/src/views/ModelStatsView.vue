<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { getPassKDashboard } from '@/api'
import type { GenerationLanguagePassK, PassKDashboardResponse, PassKValues, TranslationPairPassK } from '@/types'

use([CanvasRenderer, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent])

type PassKKey = keyof PassKValues

const languageOrder = ['C', 'C++', 'C#', 'Java', 'JavaScript', 'Python3', 'Rust', 'Golang']
const kOptions: { label: string; value: PassKKey }[] = [
  { label: 'Pass@1', value: 'pass_at_1' },
  { label: 'Pass@2', value: 'pass_at_2' },
  { label: 'Pass@3', value: 'pass_at_3' },
  { label: 'Pass@4', value: 'pass_at_4' },
  { label: 'Pass@5', value: 'pass_at_5' },
]

const loading = ref(false)
const task = ref<'generation' | 'translation'>('generation')
const selectedK = ref<PassKKey>('pass_at_1')
const selectedTranslationModel = ref('')
const passk = ref<PassKDashboardResponse | null>(null)

function score(row: PassKValues, key: PassKKey) {
  return Number(row[key].toFixed(1))
}

const generationModels = computed(() => passk.value?.generation_model_names ?? [])
const translationModels = computed(() => passk.value?.translation_model_names ?? [])

const generationRows = computed<GenerationLanguagePassK[]>(() => passk.value?.generation_languages ?? [])
const translationRows = computed<TranslationPairPassK[]>(() => {
  return (passk.value?.translation_pairs ?? []).filter((row) => row.model_name === selectedTranslationModel.value)
})

const generationHeatmap = computed(() => {
  const models = generationModels.value
  if (!models.length) return null
  const rowMap: Record<string, GenerationLanguagePassK> = {}
  generationRows.value.forEach((row) => {
    rowMap[`${row.model_name}@@${row.language}`] = row
  })
  const data: number[][] = []
  languageOrder.forEach((language, yIndex) => {
    models.forEach((model, xIndex) => {
      const row = rowMap[`${model}@@${language}`]
      data.push([xIndex, yIndex, row ? score(row, selectedK.value) : 0])
    })
  })
  return {
    tooltip: { position: 'top', formatter: (params: any) => `${models[params.value[0]]} · ${languageOrder[params.value[1]]}: ${params.value[2]}%` },
    grid: { left: 96, right: 20, top: 20, bottom: 92 },
    xAxis: { type: 'category', data: models, axisLabel: { rotate: 18, fontSize: 11 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: languageOrder, splitArea: { show: true } },
    visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 18, inRange: { color: ['#fee2e2', '#fef3c7', '#d1fae5'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params: any) => `${params.value[2]}%`, fontSize: 9 } }],
  }
})

const translationLanguages = computed(() => {
  const set = new Set<string>()
  translationRows.value.forEach((row) => {
    set.add(row.src_lang)
    set.add(row.tgt_lang)
  })
  return languageOrder.filter((language) => set.has(language))
})

const translationHeatmap = computed(() => {
  const languages = translationLanguages.value
  if (!selectedTranslationModel.value || !languages.length) return null
  const map: Record<string, TranslationPairPassK> = {}
  translationRows.value.forEach((row) => {
    map[`${row.src_lang}@@${row.tgt_lang}`] = row
  })
  const data: number[][] = []
  languages.forEach((src, yIndex) => {
    languages.forEach((tgt, xIndex) => {
      const row = map[`${src}@@${tgt}`]
      if (src !== tgt) data.push([xIndex, yIndex, row ? score(row, selectedK.value) : 0])
    })
  })
  return {
    tooltip: { position: 'top', formatter: (params: any) => `${languages[params.value[1]]} → ${languages[params.value[0]]}: ${params.value[2]}%` },
    grid: { left: 96, right: 20, top: 20, bottom: 72 },
    xAxis: { type: 'category', data: languages, splitArea: { show: true } },
    yAxis: { type: 'category', data: languages, splitArea: { show: true } },
    visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 12, inRange: { color: ['#fee2e2', '#fef3c7', '#d1fae5'] } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params: any) => `${params.value[2]}%`, fontSize: 10 } }],
  }
})

watch(passk, (value) => {
  selectedTranslationModel.value = value?.translation_model_names?.[0] ?? ''
})

onMounted(async () => {
  loading.value = true
  try {
    passk.value = (await getPassKDashboard()).data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <div class="matrix-controls">
      <el-segmented v-model="task" :options="[{ label: 'Generation', value: 'generation' }, { label: 'Translation', value: 'translation' }]" />
      <el-select v-model="selectedK" style="width: 140px">
        <el-option v-for="item in kOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-if="task === 'translation'" v-model="selectedTranslationModel" filterable style="width: 280px">
        <el-option v-for="model in translationModels" :key="model" :label="model" :value="model" />
      </el-select>
    </div>

    <div class="card">
      <div class="card-title">{{ task === 'generation' ? 'Model × Language Generation Pass@k' : 'Translation Pair Pass@k' }}</div>
      <v-chart v-if="task === 'generation' && generationHeatmap" :option="generationHeatmap" style="height: 520px" autoresize />
      <v-chart v-else-if="task === 'translation' && translationHeatmap" :option="translationHeatmap" style="height: 520px" autoresize />
      <div v-else class="empty-state">No Pass@k data</div>
    </div>
  </div>
</template>
