<script setup lang="ts">
// 原版可视化：整页内嵌。
// 基址优先级：构建变量 VITE_LEGACY_BASE（如 /legacy）→ URL ?legacyPort= → 默认 host:8092。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { locale } from '@/i18n'

const route = useRoute()
const STORAGE_KEY = 'mcibench.legacyPort'
const base = (import.meta.env.VITE_LEGACY_BASE as string | undefined) || ''

function resolvePort(): string {
  const query = route.query.legacyPort
  if (typeof query === 'string' && /^\d+$/.test(query)) {
    try { localStorage.setItem(STORAGE_KEY, query) } catch { /* 隐私模式下忽略 */ }
    return query
  }
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && /^\d+$/.test(saved)) return saved
  } catch { /* ignore */ }
  return '8092'
}

const target = computed(() => {
  const raw = route.query.view
  const view = typeof raw === 'string' && raw.startsWith('/') ? raw : '/'
  const lang = locale.value === 'en' ? 'en' : 'zh'
  if (base) {
    const path = base.replace(/\/$/, '') + (view === '/' ? '/' : view)
    return path + '?embed=1&lang=' + lang
  }
  const host = typeof location === 'undefined' ? '127.0.0.1' : location.hostname
  return 'http://' + host + ':' + resolvePort() + view + '?embed=1&lang=' + lang
})
</script>

<template>
  <iframe class="legacy-frame" :src="target" title="MCIBench benchmark visualisation" />
</template>

<style scoped>
.legacy-frame {
  display: block;
  width: calc(100% + 48px);
  height: calc(100vh - var(--header-height));
  margin: -24px;
  border: 0;
  background: #fff;
}
</style>
