<script setup lang="ts">
import { t } from '@/i18n'

import { onMounted, ref } from 'vue'
import { getModels, getSlots } from '@/api'
import type { Slot } from '@/types'
import { KLASS_LABEL, KLASS_TAG, type Klass } from '@/types'

const loading = ref(false)
const err = ref('')
const rows = ref<Slot[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const models = ref<string[]>([])

const f = ref({
  qid: '',
  model: '',
  lang: '',
  task: '',
  klass: '',
  mismatches: false,
})

const KLASSES: Klass[] = ['agrees', 'same_neg', 'false_ac', 'false_wa', 'no_corpus', 'no_lc', 'pending']
const LANGS = ['python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust']

function statusType(s: string) {
  if (s === 'Accepted') return 'success'
  if (s === 'Wrong Answer') return 'danger'
  if (s === 'Compile Error') return 'info'
  return 'warning'
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  err.value = ''
  try {
    const r = await getSlots({
      qid: f.value.qid || undefined,
      model: f.value.model || undefined,
      lang: f.value.lang || undefined,
      task: f.value.task || undefined,
      klass: f.value.klass || undefined,
      mismatches: f.value.mismatches ? '1' : undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = r.data.data
    total.value = r.data.total
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  models.value = (await getModels()).data.models
  await load()
})
</script>

<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 14px;">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <el-input v-model="f.qid" :placeholder='t("题号")' style="width:100px" clearable @change="load(true)" />
        <el-select v-model="f.model" :placeholder='t("模型")' style="width:150px" clearable @change="load(true)">
          <el-option v-for="m in models" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="f.lang" :placeholder='t("语言")' style="width:130px" clearable @change="load(true)">
          <el-option v-for="l in LANGS" :key="l" :label="l" :value="l" />
        </el-select>
        <el-select v-model="f.task" :placeholder='t("任务")' style="width:120px" clearable @change="load(true)">
          <el-option :label='t("代码生成")' value="gen" />
          <el-option :label='t("代码翻译")' value="trans" />
        </el-select>
        <el-select v-model="f.klass" :placeholder='t("分类")' style="width:180px" clearable @change="load(true)">
          <el-option v-for="k in KLASSES" :key="k" :label="KLASS_LABEL[k]" :value="k" />
        </el-select>
        <el-checkbox v-model="f.mismatches" @change="load(true)">{{ t("只看判定不一致") }}</el-checkbox>
        <el-button @click="load(true)">{{ t("刷新") }}</el-button>
      </div>
    </el-card>

    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon
              style="margin-bottom:14px" />

    <el-card shadow="never">
      <template #header>
        <span style="font-weight:600">{{ t("对拍槽位") }}</span>
        <span style="font-size:12px;opacity:.6;margin-left:8px">{{ t("共") }} {{ total.toLocaleString() }} {{ t("条") }}</span>
      </template>
      <el-table :data="rows" size="small" border v-loading="loading">
        <el-table-column :label='t("题号")' width="90">
          <template #default="{ row }">
            <router-link :to="`/problems/${row.qid}`" style="color:#409eff">q{{ row.qid }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="model" :label='t("模型")' width="130" />
        <el-table-column prop="lang" :label='t("语言")' width="110" />
        <el-table-column prop="task" :label='t("任务")' width="80" />
        <el-table-column prop="cand" :label='t("候选")' width="70" align="right" />
        <el-table-column :label='t("LeetCode 判定")' width="150">
          <template #default="{ row }">
            <el-tag :type="statusType(row.leetcode)" size="small" effect="plain">{{ row.leetcode }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label='t("本地判定")' width="150">
          <template #default="{ row }">
            <el-tag :type="statusType(row.local)" size="small" effect="plain">{{ row.local }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label='t("分类")' width="170">
          <template #default="{ row }">
            <el-tag :type="(KLASS_TAG[row.klass as Klass] as any) || 'info'" size="small">
              {{ KLASS_LABEL[row.klass as Klass] || row.klass }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="has_corpus" :label='t("有语料")' width="80" align="center">
          <template #default="{ row }">{{ row.has_corpus ? '✓' : '—' }}</template>
        </el-table-column>
      </el-table>

      <div style="margin-top:14px;text-align:right">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="() => load()"
          @size-change="() => load(true)"
        />
      </div>
    </el-card>
  </div>
</template>
