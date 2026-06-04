<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getGenCode, getProblem, getSubmissions, getTranslations } from '@/api'
import type { GenCode, ProblemDetail, Submission, Translation } from '@/types'

const route = useRoute()
const qid = computed(() => String(route.params.qid || ''))

const loading = ref(true)
const problem = ref<ProblemDetail | null>(null)
const genCodes = ref<GenCode[]>([])
const translations = ref<Translation[]>([])
const submissions = ref<Submission[]>([])

const activeTab = ref('description')
const codeFilter = ref({ model: '', language: '' })
const translationFilter = ref({ model: '', src_lang: '', tgt_lang: '' })

const groupedGenCodes = computed(() => {
  const map = new Map<string, { key: string; model: string; language: string; items: GenCode[] }>()
  for (const item of genCodes.value) {
    const key = `${item.model_name}@@${item.language}`
    if (!map.has(key)) {
      map.set(key, { key, model: item.model_name, language: item.language, items: [] })
    }
    map.get(key)!.items.push(item)
  }
  return [...map.values()]
    .map((group) => ({
      ...group,
      items: group.items.sort((a, b) => a.attempt_num - b.attempt_num),
    }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.language.localeCompare(b.language))
})

const groupedTranslations = computed(() => {
  const map = new Map<string, { key: string; model: string; src: string; tgt: string; items: Translation[] }>()
  for (const item of translations.value) {
    const key = `${item.model_name}@@${item.src_lang}@@${item.tgt_lang}`
    if (!map.has(key)) {
      map.set(key, { key, model: item.model_name, src: item.src_lang, tgt: item.tgt_lang, items: [] })
    }
    map.get(key)!.items.push(item)
  }
  return [...map.values()]
    .map((group) => ({
      ...group,
      items: group.items.sort((a, b) => a.attempt_num - b.attempt_num),
    }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.src.localeCompare(b.src) || a.tgt.localeCompare(b.tgt))
})

async function fetchProblem() {
  if (!qid.value) return
  loading.value = true
  try {
    const res = await getProblem(qid.value)
    problem.value = res.data
  } finally {
    loading.value = false
  }
}

async function fetchGenCodes() {
  if (!qid.value) return
  const res = await getGenCode(qid.value, {
    model: codeFilter.value.model || undefined,
    language: codeFilter.value.language || undefined,
  })
  genCodes.value = res.data.data ?? []
}

async function fetchTranslations() {
  if (!qid.value) return
  const res = await getTranslations(qid.value, {
    model: translationFilter.value.model || undefined,
    src_lang: translationFilter.value.src_lang || undefined,
    tgt_lang: translationFilter.value.tgt_lang || undefined,
  })
  translations.value = res.data.data ?? []
}

async function fetchSubmissions() {
  if (!qid.value) return
  const res = await getSubmissions({ qid: qid.value, page: 1, page_size: 500 })
  submissions.value = res.data.data ?? []
}

async function loadAll() {
  await fetchProblem()
  await Promise.all([fetchGenCodes(), fetchTranslations(), fetchSubmissions()])
}

watch(qid, loadAll)
onMounted(loadAll)
</script>

<template>
  <div v-loading="loading">
    <div v-if="problem" class="detail-header">
      <div>
        <div class="qid">Q{{ problem.qid }}</div>
        <h1>{{ problem.title }}</h1>
        <div class="meta-row">
          <el-tag v-if="problem.is_generation_benchmark" type="success" effect="plain">Code Generation Benchmark</el-tag>
          <el-tag v-if="problem.is_translation_benchmark" type="warning" effect="plain">Code Translation Benchmark</el-tag>
          <el-tag v-if="problem.tid" type="info" effect="plain">LeetCode {{ problem.tid }}</el-tag>
          <a v-if="problem.url" :href="problem.url" target="_blank">Open Problem</a>
        </div>
      </div>
    </div>

    <el-tabs v-if="problem" v-model="activeTab">
      <el-tab-pane label="Description" name="description">
        <div class="card prose">
          <pre>{{ problem.description }}</pre>
        </div>
      </el-tab-pane>

      <el-tab-pane label="Interfaces" name="interfaces">
        <div class="code-grid">
          <div v-for="snippet in problem.snippets" :key="snippet.id" class="card code-card">
            <div class="code-title">{{ snippet.language }}</div>
            <pre>{{ snippet.code }}</pre>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="References" name="references">
        <div class="code-grid">
          <div v-for="reference in problem.references" :key="reference.id" class="card code-card">
            <div class="code-title">{{ reference.language }} · ans{{ reference.attempt_num }}</div>
            <pre>{{ reference.code }}</pre>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="problem.is_generation_benchmark" label="Generated Codes" name="gencodes">
        <div class="filter-row">
          <el-input v-model="codeFilter.model" placeholder="Model" clearable style="width: 180px" />
          <el-input v-model="codeFilter.language" placeholder="Language" clearable style="width: 160px" />
          <el-button type="primary" @click="fetchGenCodes">Search</el-button>
        </div>
        <div v-if="groupedGenCodes.length" class="group-list">
          <div v-for="group in groupedGenCodes" :key="group.key" class="card code-group">
            <div class="group-title">
              <span>{{ group.model }} · {{ group.language }}</span>
              <el-tag effect="plain" size="small">{{ group.items.length }} answers</el-tag>
            </div>
            <el-tabs class="answer-tabs">
              <el-tab-pane v-for="item in group.items" :key="item.id" :label="`ans${item.attempt_num}`">
                <pre>{{ item.code }}</pre>
              </el-tab-pane>
            </el-tabs>
          </div>
        </div>
        <div v-else class="empty-state">No generated code records</div>
      </el-tab-pane>

      <el-tab-pane v-if="problem.is_translation_benchmark" label="Translation Results" name="translations">
        <div class="filter-row">
          <el-input v-model="translationFilter.model" placeholder="Model" clearable style="width: 180px" />
          <el-input v-model="translationFilter.src_lang" placeholder="Source Lang" clearable style="width: 150px" />
          <el-input v-model="translationFilter.tgt_lang" placeholder="Target Lang" clearable style="width: 150px" />
          <el-button type="primary" @click="fetchTranslations">Search</el-button>
        </div>
        <div v-if="groupedTranslations.length" class="group-list">
          <div v-for="group in groupedTranslations" :key="group.key" class="card code-group">
            <div class="group-title">
              <span>{{ group.model }} · {{ group.src }} → {{ group.tgt }}</span>
              <el-tag effect="plain" size="small">{{ group.items.length }} answers</el-tag>
            </div>
            <el-tabs class="answer-tabs">
              <el-tab-pane v-for="item in group.items" :key="item.id" :label="`ans${item.attempt_num}`">
                <pre>{{ item.code }}</pre>
              </el-tab-pane>
            </el-tabs>
          </div>
        </div>
        <div v-else class="empty-state">No translation result records</div>
      </el-tab-pane>

      <el-tab-pane label="Submissions" name="submissions">
        <div class="card" style="padding: 0; overflow: hidden;">
          <el-table :data="submissions" stripe style="width: 100%">
            <el-table-column prop="model_name" label="Model" min-width="160" />
            <el-table-column prop="source_type" label="Task" width="120">
              <template #default="{ row }">
                <el-tag :type="row.source_type === 'translation' ? 'warning' : 'success'" effect="plain">
                  {{ row.source_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="language" label="Language" width="120" />
            <el-table-column label="Direction" width="170">
              <template #default="{ row }">
                <span v-if="row.source_type === 'translation'">{{ row.src_lang }} → {{ row.tgt_lang }}</span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="attempt_num" label="Attempt" width="90" />
            <el-table-column prop="ac_status" label="Status" width="180" />
            <el-table-column prop="runtime" label="Runtime" width="120" />
            <el-table-column prop="memory" label="Memory" width="120" />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.detail-header {
  margin-bottom: 18px;
}

.qid {
  color: var(--color-text-secondary);
  font-weight: 700;
  margin-bottom: 4px;
}

h1 {
  margin: 0 0 10px;
}

.meta-row,
.filter-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-row a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
}

.prose pre,
.code-card pre {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.code-grid,
.group-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}

.code-card {
  overflow: hidden;
}

.code-title {
  font-weight: 700;
  margin-bottom: 10px;
}

.group-list {
  grid-template-columns: 1fr;
}

.code-group {
  overflow: hidden;
}

.group-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}

.answer-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}
</style>
