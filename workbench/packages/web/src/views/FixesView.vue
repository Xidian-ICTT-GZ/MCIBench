<script setup lang="ts">
import { t, problemTitle } from '@/i18n'

import { onMounted, ref } from 'vue'
import { getFixes } from '@/api'
import type { CorpusFix } from '@/types'

const loading = ref(true)
const err = ref('')
const rows = ref<CorpusFix[]>([])

const KIND_COLOR: Record<string, string> = {
  'A 输入保证': 'danger',
  'B 任意合法答案': 'warning',
  'C int64': 'success',
  'D/E 规模': 'primary',
  'E 规模': 'primary',
  'E 定向搜索': 'info',
}

function kindType(k: string) {
  const hit = Object.keys(KIND_COLOR).find((x) => k.startsWith(x.slice(0, 1)))
  return hit ? KIND_COLOR[hit] : 'info'
}

onMounted(async () => {
  try {
    rows.value = (await getFixes()).data.data
  } catch (e: any) {
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="err" type="error" :title="t('加载失败：{0}', [t(err)])" :closable="false" show-icon />

    <el-card shadow="never" style="margin-bottom: 14px;">
      <div style="font-size:13px;line-height:1.9">
        <b>{{ t("历史语料修复记录，不代表当前版本已完成验收。") }}</b>
        {{ t("「本地过 / LC 不过」说明本地用例太弱（覆盖不足），需要") }}<strong>{{ t("补") }}</strong>{{ t("用例； 「本地不过 / LC 过」说明本地判得太严或判题器有缺陷，需要") }}<strong>{{ t("改") }}</strong>{{ t("语料或比较语义。 记录中的数字来自当时的实验；当前有效覆盖和一致性指标请以总览中的当前版本结果为准。") }}
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="rows" size="small" border>
        <el-table-column :label='t("题号")' width="90">
          <template #default="{ row }">
            <router-link :to="`/problems/${row.qid}`" style="color:#409eff">q{{ row.qid }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="title" :label='t("标题")' width="240" ><template #default="{ row }">{{ problemTitle(row) }}</template></el-table-column>
        <el-table-column :label='t("类别")' width="160">
          <template #default="{ row }">
            <el-tag :type="kindType(row.kind) as any" size="small" effect="plain">{{ t(row.kind) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="corpus_cases" :label='t("现有语料")' width="90" align="right" />
        <el-table-column prop="note" :label='t("历史修复内容与当时记录")' ><template #default="{ row }">{{ t(row.note) }}</template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
