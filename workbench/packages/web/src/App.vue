<script setup lang="ts">
import { t, locale } from '@/i18n'
import LanguageToggle from '@/components/LanguageToggle.vue'
import en from 'element-plus/es/locale/lang/en'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import { useRouter, useRoute } from 'vue-router'
import { computed, ref, watchEffect } from 'vue'
import { currentUser, authEnabled, forgetSession } from '@/session'
import { logout as apiLogout } from '@/api/auth'

async function signOut() {
  try { await apiLogout() } catch { /* the session may already be gone */ }
  forgetSession()
  router.replace('/login')
}

const router = useRouter()
const route = useRoute()
const isCover = computed(() => route.meta.layout === 'cover')

const navItems = computed(() =>
  router.getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden)
    .map((r) => ({
      path: r.path,
      title: t(r.meta.title as string),
      icon: r.meta.icon as string,
      children: (r.meta.children as any[]) || null,
    }))
)

const currentTitle = computed(() => t((route.meta?.title as string) || '本地判题'))
watchEffect(() => {
  document.title = `${currentTitle.value} - MCIBench`
})

// 分组默认收起；只有已经处在组内页面时才自动展开，避免当前项被藏起来。
const expanded = ref<Record<string, boolean>>({})
const isOpen = (path: string) => expanded.value[path] === true
const toggle = (path: string) => { expanded.value[path] = !isOpen(path) }
watchEffect(() => { if (route.path === '/legacy') expanded.value['/legacy'] = true })

const iconMap: Record<string, string> = {
  Experiment: '🧪',
  Odometer: '📊',
  ScaleToOriginal: '⚖️',
  List: '🧾',
  Document: '📋',
  Tools: '🔧',
  DataAnalysis: '📉',
  DataBoard: '🗂️',
  Histogram: '📈',
}
</script>

<template>
  <el-config-provider :locale="locale === 'en' ? en : zhCn">
  <router-view v-if="isCover" />
  <div v-else class="app-layout">
    <aside class="app-sidebar">
      <div class="sidebar-logo">
        <div class="logo-icon">L</div>
        <div>
          <div class="logo-text">MCIBench</div>
          <div class="logo-sub">{{ t("多语言代码质量评测") }}</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        <template v-for="item in navItems" :key="item.path">
          <router-link
            v-if="!item.children"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
          >
            <span class="nav-icon">{{ iconMap[item.icon] || '📄' }}</span>
            <span>{{ item.title }}</span>
          </router-link>
          <div v-else class="nav-group">
            <div class="nav-item" :class="{ active: route.path === item.path }" @click="toggle(item.path)">
              <span class="nav-icon">{{ iconMap[item.icon] || '📄' }}</span>
              <span class="nav-label">{{ item.title }}</span>
              <span class="nav-chevron" :class="{ open: isOpen(item.path) }">▸</span>
            </div>
            <template v-if="isOpen(item.path)">
              <router-link
                v-for="child in item.children"
                :key="child.path"
                :to="child.path"
                class="nav-item nav-child"
                :class="{ active: route.fullPath === child.path }"
              >
                <span class="nav-icon">{{ iconMap[child.icon] || '·' }}</span>
                <span>{{ t(child.title) }}</span>
              </router-link>
            </template>
          </div>
        </template>
      </nav>
      <router-link to="/" class="back-to-cover">{{ t("← 平台介绍") }}</router-link>
      <div style="padding: 14px 18px; font-size: 11px; line-height: 1.6; opacity: .55;">
        {{ t("代码生成、行为不确定性与本地判题分析。") }}<br />
        {{ t("与主仪表盘（:8080）相互独立，可同时运行。") }}
      </div>
    </aside>

    <div class="app-main">
      <header class="app-header">
        <h2>{{ currentTitle }}</h2>
        <div style="display: flex; align-items: center; gap: 12px;">
          <LanguageToggle />
          <el-tag v-if="authEnabled && currentUser" type="success" size="small" effect="plain">
            {{ currentUser.username }} · {{ currentUser.role }}
          </el-tag>
          <el-button v-if="authEnabled && currentUser" link size="small" @click="signOut">{{ t("退出") }}</el-button>
          <el-tag type="info" size="small" effect="plain">local-judge:1</el-tag>
        </div>
      </header>
      <div class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </div>
  </div>
  </el-config-provider>
</template>

<style scoped>
.nav-item {
  text-decoration: none;
}
.nav-group { margin-bottom: 2px; }
.nav-label { flex: 1; }
.nav-chevron { font-size: 10px; opacity: .55; transition: transform .15s ease; }
.nav-chevron.open { transform: rotate(90deg); }
.nav-child { padding-left: 34px; font-size: 12.5px; font-weight: 400; }
.back-to-cover {
  color: var(--sidebar-text);
  padding: 10px 24px;
  font-size: 13px;
  text-decoration: none;
  border-top: 1px solid rgba(255, 255, 255, .08);
}
.back-to-cover:hover, .back-to-cover:focus-visible {
  color: white;
}
</style>
