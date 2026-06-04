<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getProblems } from '@/api'
import type { Problem } from '@/types'

const router = useRouter()
const route = useRoute()

const searchQuery = ref('')
const requireSubmission = ref(false)
const initialBenchmark = route.query.benchmark
const benchmarkFilter = ref<'all' | 'generation' | 'translation'>(
  initialBenchmark === 'generation' || initialBenchmark === 'translation' ? initialBenchmark : 'all'
)
const currentPage = ref(1)
const pageSize = ref(30)
const problems = ref<Problem[]>([])
const totalProblems = ref(0)
const loadingProblems = ref(true)

async function fetchProblems() {
  loadingProblems.value = true
  try {
    const res = await getProblems({
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchQuery.value || undefined,
      require_submission: requireSubmission.value,
      benchmark: benchmarkFilter.value,
    })
    problems.value = res.data.data ?? []
    totalProblems.value = res.data.total ?? 0
  } catch (e) {
    console.error('Failed to load problems:', e)
  } finally {
    loadingProblems.value = false
  }
}

watch(currentPage, fetchProblems)
watch([searchQuery, requireSubmission, benchmarkFilter], () => {
  currentPage.value = 1
  fetchProblems()
})
onMounted(fetchProblems)

function goToDetail(qid: string) {
  router.push({ name: 'detail', params: { qid } })
}
</script>

<template>
  <div>
        <div style="display: flex; gap: 12px; margin-bottom: 16px; align-items: center;">
          <el-input
            v-model="searchQuery"
            placeholder="Search by ID, title, or slug..."
            clearable
            style="width: 320px"
          />
          <div style="flex: 1" />
          <el-segmented
            v-model="benchmarkFilter"
            :options="[
              { label: 'All', value: 'all' },
              { label: 'Code Generation', value: 'generation' },
              { label: 'Code Translation', value: 'translation' },
            ]"
          />
          <el-segmented
            v-model="requireSubmission"
            :options="[
              { label: 'Only Evaluated', value: true },
              { label: 'All Problems', value: false },
            ]"
          />
          <el-tag type="info" effect="plain">{{ totalProblems }} total</el-tag>
        </div>

        <div class="card" style="padding: 0; overflow: hidden;">
          <el-table :data="problems" v-loading="loadingProblems" stripe style="width: 100%">
            <el-table-column prop="qid" label="QID" width="80" />
            <el-table-column label="Title" min-width="300">
              <template #default="{ row }">
                <a
                  style="cursor: pointer; color: var(--color-primary); font-weight: 500; text-decoration: none;"
                  @click="goToDetail(row.qid)"
                >
                  {{ row.title }}
                </a>
              </template>
            </el-table-column>
            <el-table-column prop="tid" label="LeetCode ID" width="120" />
            <el-table-column label="Benchmark" width="230">
              <template #default="{ row }">
                <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                  <el-tag v-if="row.is_generation_benchmark" size="small" type="success" effect="plain">Generation</el-tag>
                  <el-tag v-if="row.is_translation_benchmark" size="small" type="warning" effect="plain">Translation</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="slug" label="Slug" width="200" />
            <el-table-column label="Link" width="80">
              <template #default="{ row }">
                <a
                  v-if="row.url"
                  :href="row.url"
                  target="_blank"
                  style="color: var(--color-primary); text-decoration: none;"
                >
                  🔗
                </a>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="totalProblems > pageSize" style="display: flex; justify-content: center; margin-top: 16px;">
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="pageSize"
            :total="totalProblems"
            layout="prev, pager, next, total"
            background
          />
        </div>
  </div>
</template>
