import api from './index'

export type AuthRole = 'admin' | 'evaluator'

export interface AuthUser {
  id: number
  username: string
  role: AuthRole
  enabled: boolean
}

export const login = (username: string, password: string) =>
  api.post<{ user: AuthUser; expires_at: string }>('/auth/login', { username, password })

export const logout = () => api.post('/auth/logout', {})

export const me = () => api.get<{ user: AuthUser }>('/auth/me')
