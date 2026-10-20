<script setup lang="ts">
import { t, problemTitle } from '@/i18n'

import { onMounted, ref } from 'vue'
import { getProblems } from '@/api'
import type { Problem } from '@/types'

const loading = ref(false)
const err = ref('')
const rows = ref<Problem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)
const q = ref('')
const ftOnly = ref(true)
const fixedOnly = ref(false)

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  err.value = ''
  try {
    const r = await getProblems({
      q: q.value || undefined,
      ft_only: ftOnly.value ? '1' : undefined,
      fixed_only: fixedOnly.value ? '1' : undefined,
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

onMounted(() => load())
</script>

<template>
  <div>
    <el-alert type="info" :closable="false" style="margin-bottom:14px"><template #title>{{ t("这里展示历史基准与 LeetCode 对拍语料。扩展题目请进入") }} <router-link to="/lab">{{ t("生成与质量评测 → 题库") }}</router-link>{{ t("，不计入历史一致率。") }}</template></el-alert>
    <el-card shadow="never" style="margin-bottom: 14px;">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <el-input v-model="q" :placeholder='t("题号或标题")' style="width:220px" clearable
                  @keyup.enter="load(true)" @clear="load(true)" />
        <el-checkbox v-model="ftOnly" @change="load(true)">{{ t("只看 100 题评测集") }}</el-checkbox>
        <el-checkbox v-model="fixedOnly" @change="load(true)">{{ t("只看本次修过语料的题") }}</el-checkbox>
        <el-button type="primary" @click="load(true)">{{ t("搜索") }}</el-button>
        <span style="font-size:12px;opacity:.6">
          {{ t("「语料」是本地评测该题用的用例条数；0 表示不在本地评测集内（对拍时会被归为「无本地语料」）") }}
        </span>
      </div>
    </el-card>

    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon
              style="margin-bottom:14px" />

    <el-card shadow="never">
      <template #header>
        <span style="font-weight:600">{{ t("题目") }}</span>
        <span style="font-size:12px;opacity:.6;margin-left:8px">{{ t("共") }} {{ total.toLocaleString() }} {{ t("题") }}</span>
      </template>
      <el-table :data="rows" size="small" border v-loading="loading">
        <el-table-column :label='t("评测")' width="110">
          <template #default="{ row }">
            <router-link v-if="row.corpus_cases" :to="`/lab?qid=${row.qid}`" style="color:#409eff">{{ t("生成并评测") }}</router-link>
            <span v-else style="opacity:.35">{{ t("暂无语料") }}</span>
          </template>
        </el-table-column>
        <el-table-column :label='t("题号")' width="90">
          <template #default="{ row }">
            <router-link :to="`/problems/${row.qid}`" style="color:#409eff">q{{ row.qid }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="title" :label='t("标题")' min-width="240" ><template #default="{ row }">{{ problemTitle(row) }}</template></el-table-column>
        <el-table-column prop="difficulty" :label='t("难度")' width="100">
          <template #default="{ row }">
            <span v-if="row.difficulty">{{ row.difficulty }}</span>
            <span v-else style="opacity:.35">—</span>
          </template>
        </el-table-column>
        <el-table-column :label='t("评测集")' width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.in_ft_test" type="success" size="small" effect="plain">{{ t("是") }}</el-tag>
            <span v-else style="opacity:.35">—</span>
          </template>
        </el-table-column>
        <el-table-column :label='t("语料条数")' width="110" align="right">
          <template #default="{ row }">
            <b v-if="row.corpus_cases" style="color:#409eff">{{ row.corpus_cases }}</b>
            <span v-else style="opacity:.35">{{ t("无") }}</span>
          </template>
        </el-table-column>
        <el-table-column :label='t("基准题")' width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_generation_benchmark" size="small" effect="plain" style="margin-right:4px">{{ t("生成") }}</el-tag>
            <el-tag v-if="row.is_translation_benchmark" size="small" type="warning" effect="plain">{{ t("翻译") }}</el-tag>
            <span v-if="!row.is_generation_benchmark && !row.is_translation_benchmark" style="opacity:.35">—</span>
          </template>
        </el-table-column>
        <el-table-column :label='t("链接")' width="90" align="center">
          <template #default="{ row }">
            <a v-if="row.url" :href="row.url" target="_blank" style="color:#409eff">LeetCode</a>
            <span v-else style="opacity:.35">—</span>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top:14px;text-align:right">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[30, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="() => load()"
          @size-change="() => load(true)"
        />
      </div>
    </el-card>
  </div>
</template>
