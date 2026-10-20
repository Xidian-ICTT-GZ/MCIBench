import api from './index'
import type { Catalog, LabJob, JobSpec, ModelProfile, MatrixComparison, GeneratedSource } from '@/types/lab'

export const catalog = () => api.get<Catalog>('/lab/catalog')
export const listSources = (qid: number, language?: string) => api.get<{ data: GeneratedSource[] }>('/lab/sources', { params: { qid, language } })
export const listProfiles = () => api.get<{ data: ModelProfile[] }>('/lab/models')
export const saveProfile = (data: Partial<ModelProfile> & { api_key?: string; clear_api_key?: boolean }, id?: string) =>
  id ? api.put<ModelProfile>(`/lab/models/${id}`, data) : api.post<ModelProfile>('/lab/models', data)
export const deleteProfile = (id: string) => api.delete(`/lab/models/${id}`)
export const listJobs = (q = '', state = '', limit = 20, offset = 0) =>
  api.get<{ data: LabJob[]; total: number }>('/lab/jobs', { params: { q, state, limit, offset } })
export const getJob = (id: string) => api.get<LabJob>(`/lab/jobs/${id}`)
export const createJob = (title: string, spec: JobSpec) => api.post<LabJob>('/lab/jobs', { title, spec })
export const updateJob = (id: string, title: string, spec?: JobSpec) => api.put<LabJob>(`/lab/jobs/${id}`, { title, ...(spec ? { spec } : {}) })
export const deleteJob = (id: string) => api.delete(`/lab/jobs/${id}`)
export const runJob = (id: string) => api.post<LabJob>(`/lab/jobs/${id}/run`, {})
export const cancelJob = (id: string) => api.post<LabJob>(`/lab/jobs/${id}/cancel`, {})
export const cloneJob = (id: string) => api.post<LabJob>(`/lab/jobs/${id}/clone`, {})
export const resumeJob = (id: string) => api.post<LabJob>(`/lab/jobs/${id}/resume`, {})
export const rejudgeJob = (id: string, body: { group: number; candidate: number; corpus_mode: 'frozen' | 'current' }) =>
  api.post<LabJob>(`/lab/jobs/${id}/rejudge`, body)
export const reportHref = (id: string, lang: string) =>
  `/api/v1/lab/jobs/${id}/report?format=html&lang=${encodeURIComponent(lang)}`
export const compareCell = (id: string, group: number, left: number, right: number) =>
  api.get<MatrixComparison>(`/lab/jobs/${id}/compare`, { params: { group, left, right } })
