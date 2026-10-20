<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { t, locale } from '@/i18n'
import LanguageToggle from '@/components/LanguageToggle.vue'
import * as authApi from '@/api/auth'
import { currentUser, authEnabled } from '@/session'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)

async function submit() {
  if (busy.value) return
  busy.value = true
  try {
    const { data } = await authApi.login(username.value.trim(), password.value)
    currentUser.value = data.user
    authEnabled.value = true
    password.value = ''
    const next = typeof route.query.next === 'string' ? route.query.next : '/lab'
    await router.replace(next)
  } catch (error: any) {
    const status = error?.response?.status
    if (status === 429) ElMessage.error(t('尝试次数过多，请稍后再试'))
    else if (status === 403) ElMessage.error(t('账号已停用'))
    else ElMessage.error(t('账号或密码不正确'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-head"><LanguageToggle /></div>
    <el-card class="login-card" shadow="never">
      <h1>MCIBench</h1>
      <p class="muted">{{ t('本地判题工作台需要登录。账号由管理员创建，不开放自助注册。') }}</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item :label="t('账号')">
          <el-input v-model="username" autocomplete="username" :placeholder="t('请输入账号')" />
        </el-form-item>
        <el-form-item :label="t('密码')">
          <el-input v-model="password" type="password" show-password autocomplete="current-password"
                    :placeholder="t('请输入密码')" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" :loading="busy" style="width: 100%" @click="submit">{{ t('登录') }}</el-button>
      </el-form>
      <p class="muted note">{{ locale === 'en' ? 'Sessions last 8 hours by default; signing out or disabling an account ends them immediately.' : '会话默认 8 小时；退出或停用账号会立即失效。' }}</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f5f7fb; position: relative; }
.login-head { position: absolute; top: 20px; right: 24px; }
.login-card { width: 380px; padding: 8px 8px 0; }
.login-card h1 { margin: 0 0 6px; font-size: 22px; }
.note { margin-top: 14px; font-size: 12px; line-height: 1.6; }
.muted { color: #64748b; }
</style>
