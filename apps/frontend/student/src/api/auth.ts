import { api, setToken, clearToken } from './client'

export type UserPublic = {
  id: number
  email?: string | null
  phone?: string | null
  nickname?: string | null
  role: string
  created_at?: string | null
}

export type TokenResponse = {
  access_token: string
  token_type: string
  user: UserPublic
}

const USER_KEY = 'student_user'

export function saveSession(data: TokenResponse) {
  setToken(data.access_token)
  localStorage.setItem(USER_KEY, JSON.stringify(data.user))
}

export function loadCachedUser(): UserPublic | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserPublic
  } catch {
    return null
  }
}

export function clearSession() {
  clearToken()
  localStorage.removeItem(USER_KEY)
  // 清除本机答卷草稿等（按 user 前缀）
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && k.startsWith('draft:')) keys.push(k)
  }
  keys.forEach((k) => localStorage.removeItem(k))
}

export const authApi = {
  register: (data: {
    email?: string
    phone?: string
    password: string
    nickname?: string
  }) => api.post<TokenResponse>('/auth/register', data),

  login: (data: { account: string; password: string }) =>
    api.post<TokenResponse>('/auth/login', data),

  me: () => api.get<UserPublic>('/auth/me'),

  updateMe: (data: { nickname?: string; password?: string }) =>
    api.put<UserPublic>('/auth/me', data),
}
