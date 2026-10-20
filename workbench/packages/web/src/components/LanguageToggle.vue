<script setup lang="ts">
import { locale, setLocale } from '@/i18n'

const options = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en', label: 'English' },
] as const

function onChange(event: Event) {
  const target = event.target as HTMLSelectElement
  setLocale(target.value === 'zh-CN' ? 'zh-CN' : 'en')
}
</script>

<template>
  <label class="language-select">
    <span class="language-select__label">Language</span>
    <span class="language-select__control">
      <select :value="locale" aria-label="Language" @change="onChange">
        <option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <span class="language-select__caret" aria-hidden="true">▾</span>
    </span>
  </label>
</template>

<style scoped>
.language-select { display:inline-flex; align-items:center; gap:6px; flex-shrink:0; font-size:12px; color:var(--el-text-color-regular); white-space:nowrap }
.language-select__label { font-weight:500; letter-spacing:.02em }
.language-select__control { position:relative; display:inline-flex; align-items:center }
.language-select select { appearance:none; min-height:32px; padding:6px 26px 6px 10px; border:1px solid var(--el-border-color); border-radius:var(--el-border-radius-base); background:var(--bg-card); color:var(--el-text-color-regular); font-family:inherit; font-size:12px; font-weight:500; line-height:1.4; cursor:pointer }
.language-select select:hover { color:var(--el-color-primary); border-color:var(--el-color-primary) }
.language-select select:focus-visible { outline:2px solid var(--el-color-primary); outline-offset:3px }
.language-select__caret { position:absolute; right:9px; pointer-events:none; font-size:10px; color:var(--el-text-color-secondary) }
</style>
