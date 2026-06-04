<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { getModels, getSubmissions } from '@/api'
import type { Submission } from '@/types'

const loading = ref(false)
const submissions = ref<Submission[]>([])
const models = ref<string[]>([])
const languages = ['C', 'C++', 'C#', 'Java', 'JavaScript', 'Python3', 'Rust', 'Golang']
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)

const filters = ref({
  model: '',
  language: '',
  source_type: '',
  src_lang: '',
  tgt_lang: '',
  status: '',
})

function statusClass(status: string): string {
  if (status === 'Accepted') return 'accepted'
  if (status?.includes('Wrong')) return 'wrong'
  if (status?.includes('Time')) return 'tle'
  if (status?.includes('Error')) return 'other'
  return 'other'
}

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (filters.value.model) params.model = filters.value.model
    if (filters.value.language) params.language = filters.value.language
    if (filters.value.source_type) params.source_type = filters.value.source_type
    if (filters.value.src_lang) params.src_lang = filters.value.src_lang
    if (filters.value.tgt_lang) params.tgt_lang = filters.value.tgt_lang
    if (filters.value.status) params.status = filters.value.status

    const res = await getSubmissions(params as any)
    submissions.value = res.data.data ?? []
    total.value = res.data.total ?? 0
  } catch (error) {
    console.error('Failed to fetch submissions:', error)
  } finally {
    loading.value = false
  }
}

watch([page, filters], () => {
  fetchData()
}, { deep: true })

onMounted(async () => {
  const res = await getModels()
  models.value = res.data.data ?? []
  fetchData()
})
</script>

<template>
  <div>
    <div class="matrix-controls">
      <el-select v-model="filters.model" placeholder="Model" clearable style="width: 180px">
        <el-option v-for="m in models" :key="m" :label="m" :value="m" />
      </el-select>
      <el-select v-model="filters.language" placeholder="Language" clearable style="width: 160px">
        <el-option v-for="l in languages" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filters.source_type" placeholder="Task" clearable style="width: 150px">
        <el-option label="Generation" value="generation" />
        <el-option label="Translation" value="translation" />
      </el-select>
      <el-select v-model="filters.src_lang" placeholder="Source" clearable style="width: 140px">
        <el-option v-for="l in languages" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filters.tgt_lang" placeholder="Target" clearable style="width: 140px">
        <el-option v-for="l in languages" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filters.status" placeholder="Status" clearable style="width: 180px">
        <el-option label="Accepted" value="Accepted" />
        <el-option label="Wrong Answer" value="Wrong Answer" />
        <el-option label="Time Limit Exceeded" value="Time Limit Exceeded" />
        <el-option label="Runtime Error" value="Runtime Error" />
      </el-select>
      <div style="flex: 1" />
      <el-tag type="info" effect="plain">{{ total }} submissions</el-tag>
    </div>

    <div class="card" style="padding: 0; overflow: hidden;">
      <el-table :data="submissions" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="qid" label="QID" width="90" />
        <el-table-column prop="model_name" label="Model" min-width="180" />
        <el-table-column prop="source_type" label="Task" width="120">
          <template #default="{ row }">
            <el-tag :type="row.source_type === 'translation' ? 'warning' : 'success'" effect="plain">
              {{ row.source_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="language" label="Language" width="140" />
        <el-table-column label="Direction" width="180">
          <template #default="{ row }">
            <span v-if="row.source_type === 'translation'">{{ row.src_lang }} → {{ row.tgt_lang }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="attempt_num" label="Attempt" width="100" />
        <el-table-column label="Status" width="180">
          <template #default="{ row }">
            <span class="status-badge" :class="statusClass(row.ac_status)">{{ row.ac_status || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="runtime" label="Runtime" width="120" />
        <el-table-column prop="memory" label="Memory" width="120" />
      </el-table>
    </div>

    <div v-if="total > pageSize" style="display: flex; justify-content: center; margin-top: 16px;">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        background
      />
    </div>
  </div>
</template>
