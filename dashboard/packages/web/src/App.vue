<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { computed } from 'vue'

const router = useRouter()
const route = useRoute()

const navItems = computed(() =>
  router.getRoutes()
    .filter((r) => r.meta?.title && !r.meta?.hidden)
    .map((r) => ({
      path: r.path,
      title: r.meta.title as string,
      icon: r.meta.icon as string,
    }))
)

const currentTitle = computed(() => {
  return (route.meta?.title as string) || 'MCIBench'
})
// 被其它系统嵌入时（?embed=1），隐藏本应用的侧栏与标题栏，避免出现双列菜单；
// 独立访问时行为与样式完全不变。
const embedded = new URLSearchParams(location.search).has('embed')


const iconMap: Record<string, string> = {
  Odometer: '📊',
  Document: '📋',
  List: '🧾',
  DataAnalysis: '📉',
}
</script>

<template>
  <div class="app-layout" :class="{ 'is-embedded': embedded }">
    <!-- Sidebar -->
    <aside class="app-sidebar">
      <div class="sidebar-logo">
        <div class="logo-icon">M</div>
        <div>
          <div class="logo-text">MCIBench</div>
          <div class="logo-sub">Benchmark Platform</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path === item.path }"
        >
          <span class="nav-icon">{{ iconMap[item.icon] || '📄' }}</span>
          <span>{{ item.title }}</span>
        </router-link>
      </nav>
    </aside>

    <!-- Main Content -->
    <div class="app-main">
      <header class="app-header">
        <h2>{{ currentTitle }}</h2>
        <div style="display: flex; align-items: center; gap: 12px;">
          <el-tag type="info" size="small" effect="plain">v0.1.0</el-tag>
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
</template>

<style scoped>
.app-layout.is-embedded .app-sidebar,
.app-layout.is-embedded .app-header { display: none; }
.app-layout.is-embedded .app-content { padding: 16px 20px; }
.nav-item {
  text-decoration: none;
}
</style>
