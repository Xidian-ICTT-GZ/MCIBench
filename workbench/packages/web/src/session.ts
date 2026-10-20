// Session state shared by the router guard and the header.
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import type { AuthUser } from '@/api/auth'

export const currentUser = ref<AuthUser | null>(null)
// Distinguishes "authentication is switched off on the server" (404 on the auth
// routes) from "you are not logged in" (401). Without that distinction a local
// deployment with auth disabled would be redirected to a login page forever.
export const authEnabled = ref(false)

let resolved = false

export async function refreshSession(force = false): Promise<'ok' | 'denied' | 'disabled' | 'error'> {
  if (resolved && !force) {
    if (currentUser.value) return 'ok'
    return authEnabled.value ? 'denied' : 'disabled'
  }
  try {
    const { data } = await authApi.me()
    currentUser.value = data.user
    authEnabled.value = true
    resolved = true
    return 'ok'
  } catch (error: any) {
    const status = error?.response?.status
    if (status === 401 || status === 403) {
      resolved = true
      authEnabled.value = true
      currentUser.value = null
      return 'denied'
    }
    if (status === 404) {
      // Only an explicit "auth routes absent" means authentication is switched off.
      resolved = true
      authEnabled.value = false
      currentUser.value = null
      return 'disabled'
    }
    // Network error or 5xx: not evidence of anything. Do not cache the decision,
    // so the next navigation retries instead of pretending auth is disabled.
    return 'error'
  }
}

export function forgetSession() {
  currentUser.value = null
  resolved = false
}
