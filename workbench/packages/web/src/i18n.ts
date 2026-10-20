import { computed, ref, watch } from 'vue'
import en from './i18n-en.json'
import extra from './i18n-extra-en.json'
import titles from './problem-titles.json'

export type Locale = 'en' | 'zh-CN'
const storageKey = 'mcibench.locale'
function initialLocale(): Locale {
  try { return localStorage.getItem(storageKey) === 'zh-CN' ? 'zh-CN' : 'en' }
  catch { return 'en' }
}
export const locale = ref<Locale>(initialLocale())
export const isEnglish = computed(() => locale.value === 'en')
const english: Record<string, string> = Object.assign(Object.create(null), en, extra)
const patterns = Object.entries(english).filter(([key]) => /\{\d+\}/.test(key)).map(([key, value]) => {
  const indices: number[] = []
  const parts = key.split(/(\{\d+\})/).map(part => {
    if (/^\{\d+\}$/.test(part)) { indices.push(Number(part.slice(1, -1))); return '(.+?)' }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  })
  return { expression: new RegExp(`^${parts.join('')}$`, 's'), value, indices, key }
}).sort((a, b) => b.key.length - a.key.length)
export function setLocale(value: Locale) {
  locale.value = value
  try { localStorage.setItem(storageKey, value) } catch { /* Language still works without storage. */ }
}
export function t(message: string | null | undefined, values: unknown[] = []): string {
  if (message == null) return ''
  let translated = message
  if (locale.value === 'en') {
    translated = english[message] ?? message
    if (translated === message && /[\u3400-\u9fff]/.test(message)) {
      for (const pattern of patterns) {
        const match = pattern.expression.exec(message)
        if (!match) continue
        translated = pattern.value.replace(/\{(\d+)\}/g, (token, index) => {
          const capture = pattern.indices.indexOf(Number(index))
          return capture < 0 ? token : t(match[capture + 1]!)
        })
        break
      }
    }
  }
  return translated.replace(/\{(\d+)\}/g, (match, index) => index < values.length ? String(values[index] ?? '') : match)
}
export function problemTitle(problem: { qid: number; title: string }): string {
  const entry = (titles as Record<string, { en: string; zh: string }>)[String(problem.qid)]
  return entry ? (locale.value === 'en' ? entry.en : entry.zh) : problem.title
}
export function localizedLabels(labels: Record<string, string>): Record<string, string> {
  return new Proxy(labels, { get: (target, key) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(target, key) ? t(target[key]!) : Reflect.get(target, key) })
}
watch(locale, value => { document.documentElement.lang = value }, { immediate: true })
window.addEventListener('storage', event => {
  if (event.key === storageKey) locale.value = event.newValue === 'zh-CN' ? 'zh-CN' : 'en'
})
