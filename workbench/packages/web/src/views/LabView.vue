<script setup lang="ts">
import { t, locale, problemTitle } from '@/i18n'
import LanguageToggle from '@/components/LanguageToggle.vue'
import CorrectnessEvidence from '@/components/CorrectnessEvidence.vue'

import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as lab from '@/api/lab'
import type { Catalog, CatalogProblem, JobSpec, LabJob, ModelProfile, Outcome, ResultGroup, MatrixComparison, Candidate, GeneratedSource } from '@/types/lab'

const route = useRoute()
const tab = ref('jobs')
const error = ref('')
const busy = ref(false)
const saving = ref(false)
const catalog = ref<Catalog>({ problems: [], languages: [] })
const profiles = ref<ModelProfile[]>([])
const jobs = ref<LabJob[]>([])
const query = ref('')
const filterState = ref('')
const selected = ref<LabJob | null>(null)
const resultOpen = ref(false)
const comparisonOpen = ref(false)
const comparisonBusy = ref(false)
const comparison = ref<MatrixComparison | null>(null)
const onlyDifferences = ref(true)
const comparisonRows = computed(() => comparison.value?.rows.filter(r => !onlyDifferences.value || !r.matched) || [])
const jobOpen = ref(false)
const modelOpen = ref(false)
const editId = ref<string>()
const modelId = ref<string>()
const title = ref('')
const stateLabels = computed<Record<string, string>>(() => ({
  draft: t("草稿"), queued: t("排队中"), generating: t("生成中"), evaluating: t("评测中"),
  cancelling: t("取消中"), cancelled: t("已取消"), completed: t("已完成"), failed: t("失败"), interrupted: t("已中断"),
}))
const phaseLabels = computed<Record<string, string>>(() => ({ prepare: t("准备输入与环境"), input_contract: t('公开示例契约'), native_adapter: t('原生接口门禁'), testcase_generation: t("自动构建补充测试"), source_probe: t("源程序探测"), generation: t("模型生成"), probe: t("行为探测"), metamorphic: t("变形关系检查"), validation: t("独立验证"), full_corpus: t('完整语料独立复判'), metrics: t("指标计算") }))
const active = (state: string) => ['queued', 'generating', 'evaluating', 'cancelling'].includes(state)
const langLabel = (key: string) => catalog.value.languages.find(x => x.key === key)?.label || key
const modelLabel = (key: string) => t(profiles.value.find(x => x.id === key)?.name) || t("历史模型配置")
const pct = (n?: number | null) => n == null ? t("待计算") : `${(n * 100).toFixed(1)}%`
const uncertainty = (n?: number | null) => n == null ? t("待计算") : n.toFixed(3)
const defaults = (): JobSpec => ({ workflow_version: 'generate-translate-local-v1', source_mode: 'generate', source_candidates: {}, qids: [], model_ids: [], languages: ['python3'], task: 'gen', source_language: 'python3', num_candidates: 5, probe_count: 8, temperature: 0.7, probe_strategy: 'balanced', metamorphic_checks: true, auto_testcases: true, testcase_count: 30 })
const form = reactive<JobSpec>(defaults())
const modelForm = reactive({ name: '', model_name: '', api_url: '', key_env: '', api_key: '', clear_api_key: false, enabled: true, enable_thinking: null as boolean | null, thinking_parameter: 'auto' as NonNullable<ModelProfile['thinking_parameter']>, max_tokens: 4096 })
const sampleCount = computed(() => form.qids.length * form.model_ids.length * form.languages.length * form.num_candidates)
const readyModels = computed(() => profiles.value.filter(p => p.enabled))
const questionQuery = ref('')
const questionScope = ref('all')
const questionDifficulty = ref('')
const questionPage = ref(1)
const pickerScope = ref('all')
const generatedSources = ref<Record<string, GeneratedSource[]>>({})
const sourceSelections = reactive<Record<string, string>>({})
const sourceLoading = ref(false)
let sourceRevision = 0
watch(() => [form.task, form.source_mode, form.source_language, form.qids.join(',')], async () => {
  const revision = ++sourceRevision
  if (form.task !== 'trans' || form.source_mode !== 'candidate') return
  sourceLoading.value = true
  try {
    const rows = await Promise.all(form.qids.map(async qid => [String(qid), (await lab.listSources(qid, form.source_language)).data.data] as const))
    if (revision === sourceRevision) generatedSources.value = Object.fromEntries(rows)
  } catch (e) { if (revision === sourceRevision) ElMessage.error(t(message(e))) }
  finally { if (revision === sourceRevision) sourceLoading.value = false }
})
function selectSource(qid: number, value: string) {
  const item = generatedSources.value[String(qid)]?.find(s => `${s.job_id}:${s.candidate_id}` === value)
  if (item) form.source_candidates = { ...form.source_candidates, [String(qid)]: { job_id: item.job_id, candidate_id: item.candidate_id } }
}
const sourceIssue = computed(() => form.task === 'trans' && form.source_mode === 'candidate'
  && form.qids.some(q => !form.source_candidates?.[String(q)]))
const fullExecution = (g: ResultGroup) => ['full-corpus-executed-v2', 'full-corpus-json-v1', 'full-corpus-native-v1', 'full-corpus-mysql-v1'].includes(g.correctness_evidence?.profile_version || '')
const pickerDifficulty = ref('')
const scopeLabel = (p: CatalogProblem) => p.lab_evidence ? p.lab_evidence.evidence_level === 'reviewed_protocol_oracles' ? t('协议语料已通过门禁') : t('独立答案语料已通过门禁') : p.generated_cases >= 12 ? t("补充测试已验证") : p.scope === 'ft100' ? t("历史基准") : p.scope === 'extension' ? t("仅公开示例") : t("按需构建判题证据")
const caseCount = (p: CatalogProblem) => p.lab_evidence?.case_count ?? p.corpus_cases
const generatedCount = (p: CatalogProblem) => p.lab_evidence?.generated_count ?? p.generated_cases
const caseLabel = (p: CatalogProblem) => p.evidence_level === 'official_examples_only' ? t("公开示例") : t("本地测试")
const matchesScope = (p: CatalogProblem, scope: string) => scope === 'all' || (scope === 'ready' ? p.ready || !!p.lab_evidence : scope === 'generated' ? generatedCount(p) >= 12 : p.scope === scope)
const questionList = computed(() => {
  const text = questionQuery.value.trim().toLowerCase()
  return catalog.value.problems.filter(p => matchesScope(p, questionScope.value)
    && (!questionDifficulty.value || p.difficulty === questionDifficulty.value)
    && (!text || `${p.qid} ${p.title} ${problemTitle(p)} ${p.tags.join(' ')}`.toLowerCase().includes(text)))
})
const questionRows = computed(() => questionList.value.slice((questionPage.value - 1) * 20, questionPage.value * 20))
watch([questionQuery, questionScope, questionDifficulty], () => { questionPage.value = 1 })
const questionOptions = computed(() => catalog.value.problems.filter(p => matchesScope(p, pickerScope.value)
  && (!pickerDifficulty.value || p.difficulty === pickerDifficulty.value) || form.qids.includes(p.qid))
  .map(p => ({ value: p.qid, label: t("q{0} {1} · {2} · {3} · {4} 用例", [p.qid, problemTitle(p), p.difficulty, scopeLabel(p), caseCount(p)]), disabled: !(p.generation_available ?? p.ready) })))
const selectedQuestions = computed(() => form.qids.map(q => catalog.value.problems.find(p => p.qid === q)).filter((p): p is CatalogProblem => !!p))
const availableLanguage = (key: string) => !form.qids.length || selectedQuestions.value.length === form.qids.length && selectedQuestions.value.every(p => (p.generation_languages || p.available_languages).includes(key))
watch(() => [form.task, form.source_language], () => {
  if (form.task !== 'trans') return
  form.languages = form.languages.filter(key => key !== form.source_language)
  if (!form.languages.length) {
    const next = catalog.value.languages.find(lang => lang.key !== form.source_language && availableLanguage(lang.key))
    if (next) form.languages = [next.key]
  }
})
const languageIssue = computed(() => form.languages.some(l => !availableLanguage(l))
  || form.task === 'trans' && (!availableLanguage(form.source_language) || form.languages.includes(form.source_language)))
const extensionSelected = computed(() => selectedQuestions.value.some(p => p.evidence_level === 'official_examples_only'))
const testcaseIssue = computed(() => !form.workflow_version && !!form.auto_testcases && selectedQuestions.value.some(p => !p.test_generation_available))
const testcaseStages = computed<Record<string, string>>(() => ({ requesting_test_inputs: t("请求模型生成输入"), input_contract_gate: t('输入约束门禁'), independent_oracle_gate: t('独立答案门禁'), native_adapter_gate: t('原生接口门禁'), native_reference_generation: t('生成独立原生参考解'), rejected_model_response: t('模型响应未通过，保留证据后重试'), test_input_response: t("校验模型响应"), test_input_progress: t("接收模型响应"), reference_gate: t("参考解门禁"), functional_regression_gate: t('功能错误与正确改写门禁'), published_generated_tests: t("补充测试已验证并入库"), reused_verified_corpus: t("复用有效补充测试") }))
function chooseQuestion(p: CatalogProblem) {
  newJob()
  form.qids = [p.qid]
  form.languages = [p.problem_kind === 'database' ? 'mysql' : p.problem_kind === 'shell' ? 'bash' : 'python3']
}
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false

function message(e: unknown) {
  const err = e as { response?: { data?: { error?: string } }; message?: string }
  return err.response?.data?.error || err.message || String(e)
}

const page = ref(1)
const pageSize = 20
const jobTotal = ref(0)

async function refresh() {
  const response = await lab.listJobs(query.value, filterState.value, pageSize, (page.value - 1) * pageSize)
  jobs.value = response.data.data
  jobTotal.value = response.data.total ?? jobs.value.length
}

function changePage(next: number) {
  page.value = next
  refresh()
}

async function poll() {
  try {
    if (jobs.value.some(j => active(j.state))) await refresh()
    if (resultOpen.value && selected.value && active(selected.value.state)) {
      selected.value = (await lab.getJob(selected.value.id)).data
    }
  } catch (e) { error.value = message(e) }
  if (!disposed) timer = setTimeout(poll, 2000)
}

async function load() {
  busy.value = true
  page.value = 1
  error.value = ''
  try {
    const [c, p] = await Promise.all([lab.catalog(), lab.listProfiles()])
    catalog.value = c.data
    profiles.value = p.data.data
    await refresh()
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}

function newJob(job?: LabJob) {
  editId.value = job?.id
  title.value = job?.title || t("代码评测 {0}", [new Date().toLocaleString(locale.value)])
  Object.assign(form, defaults(), job ? { ...JSON.parse(JSON.stringify(job.spec)), probe_strategy: job.spec.probe_strategy || 'hash', metamorphic_checks: job.spec.metamorphic_checks ?? false, auto_testcases: job.spec.auto_testcases ?? false, testcase_count: job.spec.testcase_count ?? 30 } : {})
  for (const key of Object.keys(sourceSelections)) delete sourceSelections[key]
  for (const [key, value] of Object.entries(form.source_candidates || {})) sourceSelections[key] = `${value.job_id}:${value.candidate_id}`
  const newest = readyModels.value[readyModels.value.length - 1]
  if (!job && newest) form.model_ids = [newest.id]
  if (!job && route.query.qid) form.qids = [Number(route.query.qid)]
  jobOpen.value = true
}

function translateCandidate(group: ResultGroup, candidate: Candidate) {
  if (!selected.value) return
  const parentId = selected.value.id
  newJob()
  form.qids = [group.qid]
  form.task = 'trans'
  form.source_mode = 'candidate'
  form.source_language = group.language
  form.source_candidates = { [String(group.qid)]: { job_id: parentId, candidate_id: candidate.id } }
  sourceSelections[String(group.qid)] = `${parentId}:${candidate.id}`
  const alternatives = catalog.value.problems.find(p => p.qid === group.qid)?.generation_languages || catalog.value.languages.map(l => l.key)
  form.languages = [alternatives.find(l => l !== group.language && l === 'python3') || alternatives.find(l => l !== group.language) || 'cpp']
  resultOpen.value = false
}

async function saveJob(run = false) {
  saving.value = true
  try {
    const response = editId.value ? await lab.updateJob(editId.value, title.value, { ...form }) : await lab.createJob(title.value, { ...form })
    editId.value = response.data.id
    if (run) {
      selected.value = (await lab.runJob(response.data.id)).data
      resultOpen.value = true
    }
    jobOpen.value = false
    await refresh()
    ElMessage.success(run ? t("任务已提交，正在生成与评测") : t("草稿已保存"))
  } catch (e) { ElMessage.error(t(message(e))) }
  finally { saving.value = false }
}

async function view(job: LabJob) {
  try { selected.value = (await lab.getJob(job.id)).data; resultOpen.value = true }
  catch (e) { ElMessage.error(t(message(e))) }
}

async function action(job: LabJob, name: 'run' | 'cancel' | 'clone' | 'delete' | 'rename') {
  try {
    if (name === 'run') { selected.value = (await lab.runJob(job.id)).data; resultOpen.value = true }
    if (name === 'cancel') await lab.cancelJob(job.id)
    if (name === 'clone') {
      const copy = (await lab.cloneJob(job.id)).data
      newJob(copy)
    }
    if (name === 'delete') {
      await ElMessageBox.confirm(t("删除任务“{0}”？", [t(job.title || '')]), t("删除评测任务"), { type: 'warning', confirmButtonText: t('确认'), cancelButtonText: t('取消') })
      await lab.deleteJob(job.id)
      if (selected.value?.id === job.id) resultOpen.value = false
    }
    if (name === 'rename') {
      const answer = await ElMessageBox.prompt(t("输入任务名称"), t("修改名称"), { inputValue: job.title, confirmButtonText: t('确认'), cancelButtonText: t('取消') })
      if (typeof answer === 'object') await lab.updateJob(job.id, answer.value)
    }
    await refresh()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(t(message(e))) }
}

function editModel(profile?: ModelProfile) {
  modelId.value = profile?.id
  Object.assign(modelForm, { name: '', model_name: '', api_url: '', key_env: '', api_key: '', clear_api_key: false, enabled: true, enable_thinking: null, thinking_parameter: 'auto', max_tokens: 4096 }, profile || {})
  modelOpen.value = true
}

async function saveModel() {
  saving.value = true
  try {
    await lab.saveProfile({ ...modelForm }, modelId.value)
    profiles.value = (await lab.listProfiles()).data.data
    modelOpen.value = false
    ElMessage.success(t("模型配置已保存"))
  } catch (e) { ElMessage.error(t(message(e))) }
  finally { saving.value = false }
}

async function removeModel(profile: ModelProfile) {
  try {
    await ElMessageBox.confirm(t("删除模型配置“{0}”？已完成任务中的模型快照会保留。", [profile.name]), t("删除模型配置"), { type: 'warning', confirmButtonText: t('确认'), cancelButtonText: t('取消') })
    await lab.deleteProfile(profile.id)
    profiles.value = (await lab.listProfiles()).data.data
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(t(message(e))) }
}

// Rejudge and resume specs carry a single qid/language and no model list, so the
// list view must not assume the generate-shaped spec. Reading it blindly crashed
// the whole jobs table as soon as such a task existed.
const derived = (job: LabJob) => ['rejudge', 'resume'].includes(String((job.spec as any)?.kind || ''))
const recoverable = (job: LabJob) => ['failed', 'cancelled', 'interrupted'].includes(String(job.state))

// Which languages actually have an independent reference run behind this answer.
// A language without one must be visible as missing, not implied by the group.
function answerGateSummary(evidence: any) {
  const all = ['python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust']
  const passing = new Set<string>(evidence?.reference_languages || [])
  for (const [language, row] of Object.entries(evidence?.language_gates || {})) {
    const gate = row as any
    if (gate?.gate === 'Accepted' && gate?.correct === gate?.total && !gate?.dropped_unrepresentable) {
      passing.add(language)
    }
  }
  return { passing: [...passing].sort(), missing: all.filter((language) => !passing.has(language)) }
}

function jobScope(job: LabJob) {
  const spec: any = job.spec || {}
  const qids: number[] = spec.qids || (spec.qid ? [spec.qid] : [])
  const langs: string[] = spec.languages || (spec.language ? [spec.language] : [])
  const models: string[] = spec.model_ids?.length
    ? spec.model_ids
    : (spec.resume_models || []).map((m: any) => m.id)
  return { qids, langs, models }
}

async function resumeJob(job: LabJob) {
  try {
    await ElMessageBox.confirm(
      t('将复用服务端保存的原代码与冻结语料，只重新执行判题段；不调用模型，父任务保持不变。'),
      t('恢复失败任务'), { type: 'info', confirmButtonText: t('恢复'), cancelButtonText: t('取消') })
    const created = (await lab.resumeJob(job.id)).data
    ElMessage.success(t('已创建恢复任务：') + created.title)
    await refresh()
    selected.value = created
    resultOpen.value = true
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(t(message(e))) }
}

const reportHref = computed(() => selected.value ? lab.reportHref(selected.value.id, String(locale.value || 'en')) : '#')

async function rejudgeCandidate(group: ResultGroup, candidate: Candidate) {
  if (!selected.value || active(selected.value.state)) return
  const groups = selected.value.result?.groups || []
  const body = { group: groups.indexOf(group), candidate: group.candidates.indexOf(candidate), corpus_mode: 'frozen' as const }
  try {
    await ElMessageBox.confirm(
      t('将使用服务端保存的原代码与冻结语料重新执行完整判定，不调用模型、不依赖原模型配置；父任务保持不变。'),
      t('原代码复判'), { type: 'info', confirmButtonText: t('复判'), cancelButtonText: t('取消') })
    const created = (await lab.rejudgeJob(selected.value.id, body)).data
    ElMessage.success(t('已创建复判任务：') + created.title)
    await refresh()
    selected.value = created
    resultOpen.value = true
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(t(message(e))) }
}

function download() {
  if (!selected.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(selected.value, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url; a.download = `mcibench-${selected.value.id}.json`; a.click()
  URL.revokeObjectURL(url)
}

function outcomeText(o: Outcome) {
  if (o.kind === 'value') {
    const text = JSON.stringify(o.value)
    return text.length > 150 ? text.slice(0, 150) + '…' : text
  }
  return o.exception_type || o.status
}
function probeCount(group: ResultGroup) {
  return group.metrics?.probe_count || group.probe_count || selected.value?.result?.inputs?.find(x => x.qid === group.qid)?.probes.length || 0
}
async function compareCell(group: ResultGroup, left: number, right: number) {
  if (!selected.value) return
  comparisonBusy.value = true
  comparisonOpen.value = true
  comparison.value = null
  try {
    const groups = selected.value.result?.groups || []
    comparison.value = (await lab.compareCell(selected.value.id, groups.indexOf(group), left, right)).data
    onlyDifferences.value = comparison.value.differing > 0
  } catch (e) { ElMessage.error(t(message(e))); comparisonOpen.value = false }
  finally { comparisonBusy.value = false }
}
const pretty = (value: unknown) => JSON.stringify(value, null, 2)
const preview = (value: unknown) => { const text = pretty(value) || '—'; return text.length > 500 ? text.slice(0, 500) + t("…（展开查看完整内容）") : text }
const advisedCandidate = (group: ResultGroup) => group.candidates.find(c => c.id === group.selection_advice?.candidate_id)

onMounted(async () => {
  await load()
  if (route.query.qid && !error.value) newJob()
  timer = setTimeout(poll, 2000)
})
onUnmounted(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="lab-page" v-loading="busy">
    <div class="lab-intro">
      <div><h2>{{ t("生成代码，观察行为，评估风险") }}</h2><p>{{ t("选择题目和模型，生成多份候选，查看本地验证与 Code-MUE 行为不确定性。") }}</p></div>
      <el-button type="primary" size="large" :disabled="!readyModels.length || !!error" @click="newJob()">{{ t("新建评测") }}</el-button>
    </div>
    <el-alert v-if="error" type="error" :title="t(error)" :closable="false" show-icon />
    <div v-if="catalog.counts" class="catalog-summary">
      <span>{{ t("题库总量") }} <b>{{ catalog.counts.total }}</b> {{ t("题") }}</span>
      <span>{{ t("与 LeetCode 对拍") }} <b>{{ catalog.counts.historical }}</b> {{ t("题") }}</span>
      <span>{{ t("本地语料就绪") }} <b>{{ catalog.counts.ready }}</b> {{ t("题") }}</span>
      <span v-if="catalog.counts.generated_ready">{{ t("自动补测") }} <b>{{ catalog.counts.generated_ready }}</b> {{ t("题") }}</span>
      <span v-if="catalog.counts.protocol_ready">{{ t("协议语料门禁") }} <b>{{ catalog.counts.protocol_ready }}</b> {{ t("题") }}</span>
      <span class="muted">{{ t("经审查可自动补测 {0} 题 · 其余 {1} 题仅有题面与接口模板", [catalog.counts.can_generate_tests, catalog.counts.total - catalog.counts.ready]) }}</span>
    </div>
    <el-alert v-if="catalog.warning" type="warning" :title="t(catalog.warning)" :closable="false" />
    <el-alert v-if="!profiles.length && !error" type="info" :title='t("先在“模型配置”中添加 API 地址、模型名称及密钥，再创建评测任务。")' :closable="false" />
    <el-tabs v-model="tab">
      <el-tab-pane :label='t("评测任务")' name="jobs">
        <el-card shadow="never">
          <div class="toolbar">
            <el-input v-model="query" :placeholder='t("搜索任务名称")' clearable style="width:240px" @keyup.enter="load" @clear="load" />
            <el-button type="primary" @click="load">{{ t("搜索") }}</el-button>
            <el-select v-model="filterState" :placeholder='t("全部状态")' clearable style="width:150px" @change="load">
              <el-option v-for="(label, state) in stateLabels" :key="state" :label="label" :value="state" />
            </el-select>
            <el-button @click="load">{{ t("刷新") }}</el-button>
            <span class="muted">{{ t("运行中自动更新 · 共 {0} 个任务", [jobTotal]) }}</span>
          </div>
          <div class="mobile-list">
            <el-empty v-if="!jobs.length" :description='t("暂无任务，点击“新建评测”开始")' />
            <article v-for="job in jobs" :key="job.id" class="mobile-record">
              <div class="record-title"><b>{{ t(job.title) }}</b><el-tag :type="job.state === 'completed' ? 'success' : job.state === 'failed' ? 'danger' : 'info'">{{ stateLabels[job.state] }}</el-tag></div>
              <p>q{{ jobScope(job).qids.join('、q') }} · {{ jobScope(job).langs.map(langLabel).join('、') }}</p>
              <p class="muted">{{ jobScope(job).models.map(modelLabel).join('、') }}</p>
              <el-progress v-if="active(job.state)" :percentage="job.progress" :stroke-width="5" />
              <div class="record-actions">
                <el-button link type="primary" @click="view(job)">{{ t("查看") }}</el-button>
                <el-button v-if="recoverable(job)" link type="success" @click="resumeJob(job)">{{ t("恢复") }}</el-button>
                <el-button v-if="job.state === 'draft' && !derived(job)" link type="primary" @click="newJob(job)">{{ t("编辑") }}</el-button>
                <el-button v-if="job.state === 'draft'" link type="success" @click="action(job,'run')">{{ t("运行") }}</el-button>
                <el-button v-if="active(job.state) && job.state !== 'cancelling'" link type="warning" @click="action(job,'cancel')">{{ t("取消") }}</el-button>
                <el-button v-if="!active(job.state)" link @click="action(job,'rename')">{{ t("改名") }}</el-button>
                <el-button v-if="!derived(job)" link @click="action(job,'clone')">{{ t("复制") }}</el-button>
                <el-button v-if="!active(job.state)" link type="danger" @click="action(job,'delete')">{{ t("删除") }}</el-button>
              </div>
            </article>
          </div>
          <el-table class="desktop-table" :data="jobs" :empty-text='t("暂无任务，点击“新建评测”开始")'>
            <el-table-column prop="title" :label='t("任务名称")' min-width="210" ><template #default="{ row }">{{ t(problemTitle(row)) }}</template></el-table-column>
            <el-table-column :label='t("题目 / 模型 / 语言")' min-width="240">
              <template #default="{ row }"><div>q{{ jobScope(row).qids.join('、q') }}<el-tag v-if="derived(row)" size="small" type="info" style="margin-left:6px">{{ t(row.spec.kind === 'resume' ? '恢复' : '复判') }}</el-tag></div><div class="muted">{{ jobScope(row).models.map(modelLabel).join('、') }} · {{ jobScope(row).langs.map(langLabel).join('、') }}</div></template>
            </el-table-column>
            <el-table-column :label='t("进度")' width="165"><template #default="{ row }"><el-tag :type="row.state === 'completed' ? 'success' : row.state === 'failed' ? 'danger' : 'info'">{{ stateLabels[row.state] }}</el-tag><el-progress v-if="active(row.state)" :percentage="row.progress" :stroke-width="5" /></template></el-table-column>
            <el-table-column :label='t("操作")' width="285"><template #default="{ row }">
              <el-button link type="primary" @click="view(row)">{{ t("查看") }}</el-button>
              <el-button v-if="recoverable(row)" link type="success" @click="resumeJob(row)">{{ t("恢复") }}</el-button>
              <el-button v-if="row.state === 'draft' && !derived(row)" link type="primary" @click="newJob(row)">{{ t("编辑") }}</el-button>
              <el-button v-if="row.state === 'draft'" link type="success" @click="action(row,'run')">{{ t("运行") }}</el-button>
              <el-button v-if="active(row.state) && row.state !== 'cancelling'" link type="warning" @click="action(row,'cancel')">{{ t("取消") }}</el-button>
              <el-button v-if="!active(row.state)" link @click="action(row,'rename')">{{ t("改名") }}</el-button>
              <el-button v-if="!derived(row)" link @click="action(row,'clone')">{{ t("复制") }}</el-button>
              <el-button v-if="!active(row.state)" link type="danger" @click="action(row,'delete')">{{ t("删除") }}</el-button>
            </template></el-table-column>
          </el-table>
          <el-pagination
            v-if="jobTotal > pageSize"
            :current-page="page"
            :page-size="pageSize"
            :total="jobTotal"
            layout="prev, pager, next, jumper, total"
            background
            @current-change="changePage"
          />
        </el-card>
      </el-tab-pane>
      <el-tab-pane :label='t("题库")' name="questions">
        <el-card shadow="never">
          <div class="toolbar">
            <el-input v-model="questionQuery" :placeholder='t("搜索题号、标题或算法标签")' clearable style="width:270px" />
            <el-select v-model="questionScope" :aria-label='t("题库范围")' style="width:170px"><el-option :label='t("可执行题目")' value="ready" /><el-option :label='t("已补充验证")' value="generated" /><el-option :label='t("新增扩展题")' value="extension" /><el-option :label='t("历史 100 题")' value="ft100" /><el-option :label='t("待接入题目")' value="pending" /><el-option :label='t("全部已收录")' value="all" /></el-select>
            <el-select v-model="questionDifficulty" :placeholder='t("全部难度")' clearable style="width:140px"><el-option v-for="d in ['Easy','Medium','Hard']" :key="d" :label="d" :value="d" /></el-select>
            <span class="muted">{{ questionList.length }} {{ t("题") }}</span>
          </div>
          <p class="muted note">{{ t('所有题目均可按需构建补测。经审查题使用已审查约束与独立算法；其余题使用模型提出的约束程序和分别执行的答案程序交叉核验，证据等级单独标注。补测通过仍不代表 LeetCode 隐藏测试通过。') }}</p>
          <div class="mobile-list">
            <el-empty v-if="!questionRows.length" :description='t("没有符合筛选条件的题目")' />
            <article v-for="p in questionRows" :key="p.qid" class="mobile-record">
              <div class="record-title"><b>q{{ p.qid }} {{ problemTitle(p) }}</b><el-tag :type="p.scope === 'pending' ? 'info' : p.scope === 'extension' ? 'warning' : 'success'">{{ scopeLabel(p) }}</el-tag></div>
              <p>{{ p.difficulty }} · {{ t('{0} 条{1} · 补充 {2} 条', [p.corpus_cases, caseLabel(p), p.generated_cases]) }}</p>
              <p class="muted">{{ p.tags.join(' · ') }}</p>
              <p class="muted">{{ (p.generation_languages || p.available_languages).map(langLabel).join(' / ') || t("等待门禁验证") }}</p>
              <p class="muted">{{ (p.lab_evidence || p.test_generation_available) ? t("支持评测前自动补测试") : t(p.test_generation_reason) }}</p>
              <CorrectnessEvidence :evidence="p.correctness_evidence" compact />
              <el-button link type="primary" :disabled="!(p.generation_available ?? p.ready) || !readyModels.length" @click="chooseQuestion(p)">{{ t("选题评测") }}</el-button>
            </article>
          </div>
          <el-table class="desktop-table" :data="questionRows" :empty-text='t("没有符合筛选条件的题目")'>
            <el-table-column :label='t("题目")' min-width="230"><template #default="{ row }"><b>q{{ row.qid }} {{ problemTitle(row) }}</b><div class="muted">{{ row.tags.join(' · ') }}</div></template></el-table-column>
            <el-table-column prop="difficulty" :label='t("难度")' width="95" />
            <el-table-column :label="t('正确性审计')" min-width="240"><template #default="{ row }"><CorrectnessEvidence :evidence="row.correctness_evidence" compact /></template></el-table-column>
            <el-table-column :label='t("评测依据")' min-width="230"><template #default="{ row }"><el-tag :type="generatedCount(row) ? 'success' : row.scope === 'pending' ? 'info' : 'warning'">{{ scopeLabel(row) }}</el-tag><div>{{ t('{0} 条{1} · 补充 {2} 条', [caseCount(row), caseLabel(row), generatedCount(row)]) }}</div><small class="muted">{{ (row.lab_evidence || row.test_generation_available) ? t("支持自动补测试") : t(row.test_generation_reason) }}</small></template></el-table-column>
            <el-table-column :label='t("可用语言")' min-width="180"><template #default="{ row }">{{ (row.generation_languages || row.available_languages).map(langLabel).join(' / ') || t("等待门禁验证") }}</template></el-table-column>
            <el-table-column :label='t("操作")' width="110"><template #default="{ row }"><el-button link type="primary" :disabled="!(row.generation_available ?? row.ready) || !readyModels.length" @click="chooseQuestion(row)">{{ t("选题评测") }}</el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="questionPage" :page-size="20" :total="questionList.length" layout="prev, pager, next" small />
        </el-card>
      </el-tab-pane>
      <el-tab-pane :label='t("模型配置")' name="models">
        <el-card shadow="never">
          <div class="toolbar"><el-button type="primary" @click="editModel()">{{ t("添加模型") }}</el-button><span class="muted">{{ t("支持兼容 chat/completions 的远程 API 和本地模型服务") }}</span></div>
          <div class="mobile-list">
            <el-empty v-if="!profiles.length" :description='t("添加一个可调用的模型配置")' />
            <article v-for="profile in profiles" :key="profile.id" class="mobile-record">
              <div class="record-title"><b>{{ t(profile.name) }}</b><el-tag :type="profile.enabled ? 'success' : 'info'">{{ profile.enabled ? t("启用") : t("禁用") }}</el-tag></div>
              <p>{{ profile.model_name }}</p><p class="muted endpoint">{{ profile.api_url }}</p>
              <p class="muted">{{ t("密钥：") }}{{ profile.credential_configured ? t("已配置") : t("未配置") }}</p>
              <div class="record-actions"><el-button link type="primary" @click="editModel(profile)">{{ t("编辑") }}</el-button><el-button link type="danger" @click="removeModel(profile)">{{ t("删除") }}</el-button></div>
            </article>
          </div>
          <el-table class="desktop-table" :data="profiles" :empty-text='t("添加一个可调用的模型配置")'>
            <el-table-column :label='t("显示名称")' min-width="160"><template #default="{ row }">{{ t(row.name) }}</template></el-table-column>
            <el-table-column prop="model_name" :label='t("API 模型名")' min-width="180" />
            <el-table-column prop="api_url" :label='t("API 地址")' min-width="240" />
            <el-table-column :label='t("密钥")' width="100"><template #default="{ row }">{{ row.credential_configured ? t("已配置") : t("未配置") }}</template></el-table-column>
            <el-table-column :label='t("状态")' width="90"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? t("启用") : t("禁用") }}</el-tag></template></el-table-column>
            <el-table-column :label='t("操作")' width="140"><template #default="{ row }"><el-button link type="primary" @click="editModel(row)">{{ t("编辑") }}</el-button><el-button link type="danger" @click="removeModel(row)">{{ t("删除") }}</el-button></template></el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="jobOpen" :title="editId ? t('编辑评测草稿') : t('新建评测任务')" width="740px" :close-on-click-modal="false">
      <template #header="{ titleId, titleClass }"><div class="dialog-heading"><span :id="titleId" :class="titleClass">{{ editId ? t('编辑评测草稿') : t('新建评测任务') }}</span><LanguageToggle /></div></template>
      <el-form label-position="top">
        <el-form-item :label='t("任务名称")'><el-input v-model="title" maxlength="120" /></el-form-item>
        <div class="toolbar">
          <el-select v-model="pickerScope" :aria-label='t("选题范围")' style="width:180px"><el-option :label='t("全部已收录")' value="all" /><el-option :label='t("全部可评测题目")' value="ready" /><el-option :label='t("新增扩展题")' value="extension" /><el-option :label='t("历史 100 题")' value="ft100" /></el-select>
          <el-select v-model="pickerDifficulty" :placeholder='t("全部难度")' clearable style="width:140px"><el-option v-for="d in ['Easy','Medium','Hard']" :key="d" :label="d" :value="d" /></el-select>
        </div>
        <el-form-item :label='t("题目")'><el-select-v2 v-model="form.qids" multiple filterable :options="questionOptions" :placeholder='t("按题号或标题搜索，每次最多 10 题")' style="width:100%" :multiple-limit="10" /></el-form-item>
        <div v-for="p in selectedQuestions" :key="p.qid" class="question-evidence"><b>q{{ p.qid }} · {{ scopeLabel(p) }}</b><span>{{ t('{0} 条{1} · 补充 {2} 条', [caseCount(p), caseLabel(p), generatedCount(p)]) }} · {{ (p.generation_languages || p.available_languages).map(langLabel).join(' / ') }}</span></div>
        <el-form-item :label='t("自动构建补充测试")'><el-switch v-model="form.auto_testcases" /><span class="muted candidate-tag">{{ t("评测前检查补充测试，不足时使用第一个所选模型生成输入，再执行独立答案与参考解门禁。") }}</span></el-form-item>
        <el-form-item v-if="form.auto_testcases" :label='t("每题补充输入目标数")'><el-input-number v-model="form.testcase_count" :min="12" :max="100" /><span class="muted candidate-tag">{{ t("每题补充输入最多三次调用；首次接入还需构建约束程序、独立答案程序和接口门禁。有效证据可复用。") }}</span></el-form-item>
        <el-alert v-if="testcaseIssue" type="error" :title='t("部分所选题仍缺已审查的输入约束或独立答案算法，不能自动补测试。可在题库查看缺项；关闭此开关仅能探索现有语料，不能据此声称可靠通过。")' :closable="false" />
        <el-alert v-if="extensionSelected" type="warning" :title='t("扩展题目前仅有官方示例，也会出现在生成提示词中。通常仅余 1 条分离验证输入，K 会自动缩减；通过不代表隐藏测试正确，低不确定性也可能来自覆盖不足。")' :closable="false" />
        <el-form-item :label='t("大模型")'><el-select v-model="form.model_ids" multiple style="width:100%"><el-option v-for="p in readyModels" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
        <div class="form-grid">
          <el-form-item :label='t("任务类型")'><el-radio-group v-model="form.task"><el-radio-button value="gen">{{ t("代码生成") }}</el-radio-button><el-radio-button value="trans">{{ t("代码转译") }}</el-radio-button></el-radio-group></el-form-item>
          <el-form-item v-if="form.task === 'trans'" :label='t("源语言（先生成或选择已有代码）")'><el-select v-model="form.source_language"><el-option v-for="l in catalog.languages" :key="l.key" :label="l.label" :value="l.key" :disabled="!availableLanguage(l.key)" /></el-select></el-form-item>
        </div>
        <el-form-item :label='t("目标语言")'><el-select v-model="form.languages" multiple style="width:100%"><el-option v-for="l in catalog.languages" :key="l.key" :label="l.label" :value="l.key" :disabled="!availableLanguage(l.key) || form.task === 'trans' && form.source_language === l.key" /></el-select></el-form-item>
        <template v-if="form.task === 'trans'">
          <el-form-item :label="t('翻译源代码')"><el-radio-group v-model="form.source_mode"><el-radio-button value="generate">{{ t('先生成，再翻译') }}</el-radio-button><el-radio-button value="candidate">{{ t('选择已生成候选') }}</el-radio-button></el-radio-group></el-form-item>
          <p v-if="form.source_mode === 'generate'" class="muted note">{{ t('每个模型先生成一份源语言代码，再据此生成目标语言候选。源代码和全部来源信息会保存，不使用题库参考解冒充生成结果。') }}</p>
          <template v-else>
            <el-form-item v-for="qid in form.qids" :key="qid" :label="`q${qid} · ${t('选择已生成候选')}`">
              <el-select v-model="sourceSelections[String(qid)]" filterable :loading="sourceLoading" style="width:100%" @change="(value: string) => selectSource(qid, value)">
                <el-option v-for="s in generatedSources[String(qid)] || []" :key="`${s.job_id}:${s.candidate_id}`" :value="`${s.job_id}:${s.candidate_id}`" :label="`${s.job_title} · ${s.model_name} · ${langLabel(s.language)} · ${t('候选')} ${s.candidate_index}`" />
              </el-select>
            </el-form-item>
            <el-alert v-if="sourceIssue && !sourceLoading" type="info" :title="t('请先生成所选题目和源语言的代码，再选择一份完整候选用于翻译。')" :closable="false" />
          </template>
        </template>
        <el-alert v-if="languageIssue" type="error" :title='t("所选题目尚不支持部分语言，请移除这些目标语言，或修改转译源语言。")' :closable="false" />
        <el-alert v-if="form.workflow_version" type="info" :title="t('所有收录题均可生成。代码生成后再构建独立测试并本地执行；证据不足或执行未完成会保留代码并说明原因，不报告通过。数据库题可选原生 MySQL 8.0 或 SQLite，结果记录实际方言；Shell 题提供独立文件环境。')" :closable="false" />
        <div class="form-grid triple">
          <el-form-item :label='t("每组候选数 N")'><el-input-number v-model="form.num_candidates" :min="1" :max="25" /></el-form-item>
          <el-form-item :label='t("探测输入数 K")'><el-input-number v-model="form.probe_count" :min="2" :max="20" /></el-form-item>
          <el-form-item :label='t("采样温度")'><el-input-number v-model="form.temperature" :min="0.1" :max="2" :step="0.1" /></el-form-item>
        </div>
        <el-form-item :label='t("探测输入策略")'><el-select v-model="form.probe_strategy"><el-option :label='t("覆盖优先：边界、规模与结构多样性")' value="balanced" /><el-option :label='t("输入哈希顺序：兼容旧任务")' value="hash" /></el-select></el-form-item>
        <el-form-item :label='t("变形关系检查")'><el-switch v-model="form.metamorphic_checks" /><span class="muted candidate-tag">{{ t("适用题目额外检查最多两种输入变换，增加执行时间；不计入 AC 或谱熵。目前支持 q1014、q1957。") }}</span></el-form-item>
        <el-alert :type="sampleCount > 200 ? 'error' : 'info'" :title="t('将生成 {0} 份候选代码，单任务上限 200。生成和沙箱执行需要时间，提交后可实时查看进度。', [sampleCount])" :closable="false" />
        <p class="muted note">{{ t("同题候选共享探测输入；另一组输入用于本地验证。覆盖优先保留至少三个或约 30% 的验证输入，语料少时调整；实际 K 与选择依据会记录在结果中。选择策略不读取预期答案。任务会调用所选模型 API。") }}</p>
      </el-form>
      <template #footer><el-button @click="jobOpen=false">{{ t("关闭") }}</el-button><el-button :loading="saving" :disabled="languageIssue || testcaseIssue || sourceIssue" @click="saveJob()">{{ t("保存草稿") }}</el-button><el-button type="primary" :loading="saving" :disabled="!sampleCount || sampleCount > 200 || languageIssue || testcaseIssue || sourceIssue" @click="saveJob(true)">{{ t("生成并评测") }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="modelOpen" :title="modelId ? t('编辑模型配置') : t('添加模型')" width="630px" :close-on-click-modal="false">
      <template #header="{ titleId, titleClass }"><div class="dialog-heading"><span :id="titleId" :class="titleClass">{{ modelId ? t('编辑模型配置') : t('添加模型') }}</span><LanguageToggle /></div></template>
      <el-form label-position="top">
        <div class="form-grid"><el-form-item :label='t("显示名称")'><el-input v-model="modelForm.name" :placeholder='t("例如 Qwen3-8B")' /></el-form-item><el-form-item :label='t("API 模型名")'><el-input v-model="modelForm.model_name" :placeholder='t("接口要求的 model 名称")' /></el-form-item></div>
        <el-form-item :label='t("API 地址")'><el-input v-model="modelForm.api_url" placeholder="https://provider.example/v1/chat/completions" /></el-form-item>
        <el-form-item :label='t("API 密钥")'><el-input v-model="modelForm.api_key" type="password" show-password autocomplete="new-password" :placeholder="modelId ? t('留空保留已保存的密钥') : t('本地无认证服务可留空')" /></el-form-item>
        <el-form-item :label='t("或使用服务端环境变量")'><el-input v-model="modelForm.key_env" :placeholder='t("例如 LLM_API_KEY")' /></el-form-item>
        <div class="form-grid"><el-form-item :label='t("最大生成 token")'><el-input-number v-model="modelForm.max_tokens" :min="128" :max="16384" :step="128" /></el-form-item><el-form-item :label='t("思考模式（接口支持时）")'><el-select v-model="modelForm.enable_thinking"><el-option :label='t("使用接口默认值")' :value="null" /><el-option :label='t("关闭")' :value="false" /><el-option :label='t("开启")' :value="true" /></el-select></el-form-item></div>
        <el-form-item :label='t("思考参数格式")'><el-select v-model="modelForm.thinking_parameter"><el-option :label='t("自动识别（DeepSeek 官方地址使用 thinking.type）")' value="auto" /><el-option :label='t("thinking.type（DeepSeek 或兼容代理）")' value="thinking" /><el-option :label='t("enable_thinking（Qwen 等兼容服务）")' value="enable_thinking" /></el-select></el-form-item>
        <el-checkbox v-model="modelForm.enabled">{{ t("启用模型") }}</el-checkbox><el-checkbox v-if="modelId" v-model="modelForm.clear_api_key">{{ t("清除已保存密钥") }}</el-checkbox>
        <p class="muted note">{{ t("密钥保存在本机服务端；查询结果和评测导出不包含密钥。") }}</p>
      </el-form>
      <template #footer><el-button @click="modelOpen=false">{{ t("取消") }}</el-button><el-button type="primary" :loading="saving" @click="saveModel">{{ t("保存配置") }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="resultOpen" :title="t(selected?.title || '评测结果')" size="85%">
      <template #header><div class="dialog-heading"><span>{{ t(selected?.title || '评测结果') }}</span><LanguageToggle /></div></template>
      <template v-if="selected">
        <div class="toolbar"><el-tag>{{ stateLabels[selected.state] }}</el-tag><el-button v-if="recoverable(selected)" type="success" plain @click="resumeJob(selected)">{{ t("恢复判题段") }}</el-button><el-button @click="download">{{ t("导出 JSON") }}</el-button><a :href="reportHref" target="_blank" rel="noopener" class="report-link"><el-button>{{ t("报告 HTML") }}</el-button></a><el-button v-if="active(selected.state) && selected.state !== 'cancelling'" type="warning" plain @click="action(selected,'cancel')">{{ t("取消任务") }}</el-button></div>
        <el-progress :percentage="selected.progress" :status="selected.state === 'completed' ? 'success' : undefined" />
        <p class="note">{{ t(selected.stage) }}</p>
        <p v-if="selected.result?.timing" class="muted note">{{ t("阶段耗时：准备") }} {{ ((selected.result.timing.phases_ms.prepare_ms || 0)/1000).toFixed(1) }}{{ t("s · 模型调用") }} {{ ((selected.result.timing.phases_ms.generation_ms || 0)/1000).toFixed(1) }}{{ t("s · 探测") }} {{ ((selected.result.timing.phases_ms.probe_ms || 0)/1000).toFixed(1) }}{{ t("s · 独立验证") }} {{ ((selected.result.timing.phases_ms.validation_ms || 0)/1000).toFixed(1) }}{{ t("s · 沙箱并发") }} {{ selected.result.timing.max_sandbox_concurrency }}</p>
        <el-alert v-if="selected.error" type="error" :title="t(selected.error)" :description="t(selected.result?.failure?.suggestion)" :closable="false" show-icon />
        <el-alert v-for="notice in selected.evidence_advisories || []" :key="notice.id" type="error" :closable="false" show-icon
          :title="t(notice.status === 'invalidated_execution' ? '判题执行证据已失效' : '语料证据已失效') + ' · q' + notice.qid"
          :description="notice.reason_code === 'official_word_rules_revised' ? t('旧语料依据的题面缺少现已明确的词规则，三条答案已按有来源的新版本更正；原任务和代码保留，需显式迁移后复判。') : notice.reason_code === 'parenthesized_select_rejected' ? t('旧执行器误拒合法的括号 SELECT 查询；原代码在修正后通过，旧结果保留但不应作为功能错误证据。') : notice.reason_code === 'declared_DATE_transport_mismatch' ? t('旧语料的 DATE 字段使用了不一致的日期表示；已统一格式并保留原日历值与迁移依据，旧记录不追写。') : notice.reason_code === 'single_department_N_guarantee_violated' ? t('旧语料包含单部门标为 Y 的输入，违反题面明确的 N 保证；该输入已撤下，旧任务与源码保留。') : notice.reason_code === 'native_float32_input_rounding_mismatch' ? t('旧答案未遵循已记录的 MySQL FLOAT 输入精度，临界值答案已更正；旧任务和源码保留，不作为新判定依据。') : notice.reason_code === 'binary_float_oracle_rounding_mismatch' ? t('旧答案使用二进制浮点舍入，与本次原生 MySQL 十进制规则不符；该语料已撤下，原始任务保留。') : notice.reason_code === 'main_unique_maximum_violated' ? t('该题旧语料包含违反主任务唯一最大保证的并列情况，原判定不应作为候选质量依据。旧结果保留，请使用修复后的语料复判。') : t('该任务使用的部分旧语料已撤下，请重新核验判定依据。')" />
        <p v-if="selected.result?.failure" class="muted note">{{ t("失败阶段：") }}{{ phaseLabels[selected.result.failure.phase] || selected.result.failure.phase }} · {{ selected.result.failure.code }}<template v-if="selected.result.failure.context.qid"> · q{{ selected.result.failure.context.qid }} / {{ selected.result.failure.context.model_name }} / {{ langLabel(selected.result.failure.context.language || '') }} {{ t("/ 候选") }} {{ selected.result.failure.context.candidate_index || '—' }}</template></p>
        <p v-else-if="selected.state === 'failed'" class="muted note">{{ t("该历史任务未保存详细调用响应，无法补查当时的停止原因；复制后重新运行可获得新的调用诊断。") }}</p>
        <el-alert type="info" :title='t("不确定性只比较候选行为。新任务的全部本地测试通过率同时检查验证输入和探测输入；另行保留分离验证结果，两项指标都不等于 LeetCode 判定。")' :closable="false" />
        <el-card v-if="selected.result?.verdict" shadow="never" class="group-card">
          <template #header><b>{{ t(selected.spec?.kind === 'resume' ? '恢复结果' : '复判结果') }}</b></template>
          <p class="muted note">{{ t(selected.result?.note || '') }}</p>
          <p><b>{{ t('判定') }}</b> {{ selected.result.verdict.ac_status }} · {{ selected.result.verdict.total_correct }}/{{ selected.result.verdict.total_testcases }} · <b>{{ t('模型调用') }}</b> {{ selected.result.model_calls }} · <b>{{ t('执行入口') }}</b> {{ selected.result.executor?.path || selected.result.config?.execution_path || '—' }}</p>
          <p><b>{{ t('语料') }}</b> {{ selected.result.corpus?.mode || t('父任务冻结快照') }} {{ selected.result.corpus?.cases ? '· ' + selected.result.corpus.cases + ' ' + t('条') : '' }} · <b>{{ t('父任务') }}</b> {{ selected.result.parent_job_id || selected.result.resumed_from || '—' }}</p>
          <p v-if="selected.result.first_failure" class="muted note">{{ t('首个失败用例') }} · {{ t('输入') }} {{ JSON.stringify(selected.result.first_failure.args) }} · {{ t('期望值') }} {{ JSON.stringify(selected.result.first_failure.expected) }} · {{ t('实际值未采集') }}</p>
        </el-card>
        <el-empty v-if="!selected.result?.groups?.length && !selected.result?.verdict" :description="active(selected.state) ? t('等待生成第一组候选，结果会自动更新') : t('该任务没有候选结果')" />
        <el-card v-for="s in selected.result?.source_generations || []" :key="s.candidate.id" shadow="never" class="group-card">
          <template #header><b>{{ t('源代码生成阶段') }} · q{{ s.qid }} · {{ t(s.model_name) }} · {{ langLabel(s.language) }}</b></template>
          <p class="muted note">{{ t('这份代码先由所选模型生成，再作为翻译输入；标准答案程序不会替代这份源代码。') }}</p>
          <el-tag>{{ s.candidate.generation_state === 'succeeded' ? t('已生成') : s.candidate.generation_state === 'generating' ? t('生成中') : t('生成未完成') }}</el-tag>
          <details v-if="s.candidate.code"><summary>{{ t('查看源代码') }} · SHA {{ s.candidate.code_sha256.slice(0,12) }}</summary><pre class="code">{{ s.candidate.code }}</pre></details>
          <details v-if="s.candidate.raw"><summary>{{ t('原始返回') }}</summary><pre class="code">{{ s.candidate.raw }}</pre></details>
        </el-card>
        <el-card v-if="selected.result?.testcase_workflow" shadow="never" class="group-card">
          <template #header><b>{{ t("自动构建补充测试") }}</b></template>
          <p>{{ t("目标每题") }} {{ selected.result.testcase_workflow.target_per_question }} {{ t("条补充输入 ·") }} {{ selected.result.testcase_workflow.state === 'completed' ? t("门禁完成") : selected.result.testcase_workflow.state === 'failed' ? t("构建失败，代码与断点已保留") : selected.result.testcase_workflow.state === 'cancelled' ? t("已取消构建") : selected.result.testcase_workflow.state === 'incomplete' ? t('未完成') : t("正在构建") }}</p>
          <p class="muted">{{ t("模型只生成输入，答案由独立算法核算，参考解验证后才发布。输入不合法、答案冲突、响应截断或门禁失败均不入库。尚未确认与 LeetCode 隐藏测试一致。") }}</p>
          <p v-for="q in selected.result.testcase_workflow.questions" :key="q.qid">q{{ q.qid }}：{{ q.generated_count }} {{ t("条补充输入已验证") }}<span v-if="q.effective_target !== q.requested_target"> {{ t("· 有限输入域将目标从") }} {{ q.requested_target }} {{ t("调整为") }} {{ q.effective_target }}</span></p>
          <p v-if="selected.result.testcase_workflow.events.length" class="muted">{{ t("最新阶段：") }}{{ testcaseStages[selected.result.testcase_workflow.events[selected.result.testcase_workflow.events.length - 1]!.stage] || t("测试构建") }}</p>
        </el-card>
        <el-card v-for="g in selected.result?.groups || []" :key="`${g.qid}-${g.model_id}-${g.language}`" shadow="never" class="group-card">
          <template #header><b>q{{ g.qid }} · {{ t(g.model_name) }} · {{ langLabel(g.language) }}</b></template>
          <el-alert v-if="g.corpus_evidence?.scope === 'extension' || g.corpus_evidence?.generated_count" type="warning" :title="t(g.corpus_evidence.notice)" :closable="false" />
          <CorrectnessEvidence :evidence="g.correctness_evidence" />
          <p v-if="g.behavior_semantics_version" class="muted note">{{ t('行为比较按输出契约处理表格列名和数值表示；源码编译失败与实际结果差异仍保留。') }} <code>{{ g.behavior_semantics_version }}</code></p>
          <details v-if="g.sql_evidence || g.source_sql_evidence" class="note"><summary>{{ t('原生 SQL 执行证据') }}</summary><p v-for="(sql, sqlIndex) in [g.sql_evidence, g.source_sql_evidence].filter(Boolean)" :key="sqlIndex">{{ sqlIndex === 0 && g.sql_evidence ? t('目标代码') : t('翻译源代码') }} · MySQL {{ sql!.environment.mysql_version }} · {{ t('参考门禁') }} {{ sql!.reference_gate_status }} / {{ sql!.reference_case_count }} {{ t('个测试输入') }}<br />{{ t('隔离网络') }}：{{ sql!.environment.network }} · {{ t('排序规则') }}：{{ sql!.environment.collation }}<br />{{ t('镜像指纹') }}：{{ sql!.environment.image }}<br />{{ t('题面未指定的字符串宽度和小数精度使用已记录的适配配置；尚未核实与 LC 服务配置完全相同。') }}</p></details>
          <el-alert v-if="g.judging_error" type="error" :title="t(g.judging_error)" :closable="false" />
          <p v-if="g.answer_evidence" class="muted note">{{ t('已通过参考执行') }}：{{ answerGateSummary(g.answer_evidence).passing.join('、') || t('无') }} · {{ t('尚无参考执行') }}：{{ answerGateSummary(g.answer_evidence).missing.join('、') || t('无') }}</p>
          <p v-if="g.answer_evidence" class="muted note">{{ t('答案依据') }}：{{ g.answer_evidence.evidence_level === 'reviewed_independent_oracle' ? t('经审查独立算法') : g.answer_evidence.evidence_level === 'reviewed_shell_oracle' ? t('经审查文件处理规则') : g.answer_evidence.evidence_level === 'reviewed_protocol_oracles' ? t('经审查 Python 答案与 JavaScript 参考解交叉核验') : g.answer_evidence.evidence_level === 'reviewed_sql_controller_and_executed_oracles' ? t('经审查 SQL 控制器与执行答案交叉核验') : g.answer_evidence.evidence_level === 'reviewed_controller_and_executed_oracles' ? t('已审查结构控制器与执行答案交叉核验') : t('独立执行的答案程序交叉核验') }} · {{ t('约束依据') }}：{{ g.answer_evidence.constraint_evidence === 'model_proposed_validator' ? t('模型提出的约束程序，尚未完成人工逐题审查') : g.answer_evidence.constraint_evidence === 'reviewed_declarative_protocol' ? t('已审查声明式协议与回调输入输出类型，仍有明确验证边界') : g.answer_evidence.constraint_evidence === 'reviewed_sql_input_scope' ? t('已审查 SQL 输入范围，范围外仍待核实') : g.answer_evidence.constraint_evidence === 'reviewed_controller_and_model_validator' ? t('已审查节点和 API 构造规则，附加模型约束检查') : t('已记录的题面规则与门禁') }}</p>
          <p v-if="g.answer_evidence?.evidence_level === 'reviewed_sql_controller_and_executed_oracles'" class="muted note">{{ g.qid === 1633 ? t('当前核验最多 2000 名用户、20000 条注册记录；百分比按已记录的原生十进制精度与半入规则计算。') : g.qid === 1661 ? t('当前核验最多 2000 条事件，时间戳按原生 FLOAT 精度转换；仅覆盖已证明累加精度稳定的输入，其他合法数值范围仍待核实。') : t('SQL 控制器当前验证不超过 2000 行；范围外输入仍待核实。') }}<span v-if="g.qid === 1211"> {{ t('数值按已记录的 MySQL 十进制除法、平均值精度及半入规则计算；仅审查无大小写分组冲突的 ASCII 名称。') }}</span><span v-if="g.qid === 1517"> {{ t('邮箱前缀限规定的 ASCII 字符，域名严格区分大小写，不接受末尾空白或换行。') }}</span></p>
          <p v-if="g.qid === 1484 && g.sql_evidence" class="muted note">{{ t('商品名按现有可移植契约区分大小写并排序；原生参考显式采用相同规则，尚未核实与 LC 排序配置完全相同。') }}</p>
          <p v-if="g.qid === 1693 && g.answer_evidence" class="muted note">{{ t('声明为 DATE 的日期按 YYYY-MM-DD 传输，普通文本不改写；原日期表示与迁移依据均保留。') }}</p>
          <p v-if="g.qid === 1789 && g.answer_evidence" class="muted note">{{ t('单部门必须标 N，多部门仅有一个主部门 Y；新输入同时经过独立规则与执行门禁。') }}</p>
          <p v-if="g.qid === 1873 && g.answer_evidence" class="muted note">{{ t('奖金条件按字面字符 M 区分大小写，原生参考显式采用相同规则；与 LC 排序设置的一致性仍待核实。') }}</p>
          <p v-if="g.qid === 1934 && g.answer_evidence?.evidence_level === 'reviewed_sql_controller_and_executed_oracles'" class="muted note">{{ t('确认率按精确计数比半入保留两位，无请求为零；时间传输仅核验整秒规范格式，其他合法表示仍待核实。') }}</p>
          <p v-if="g.qid === 3374 && g.answer_evidence?.statement_revision" class="muted note">{{ t('按已核实的新版官方规则分词：非字母开头的词不改，仅完整的字母连字符结构逐段大写，其余词只处理首字母。') }}</p>
          <p v-if="g.qid === 3436 && g.answer_evidence?.evidence_level === 'reviewed_sql_controller_and_executed_oracles'" class="muted note">{{ t('邮箱按 ASCII 非空段与精确小写 .com 核验，不接受末尾空白或换行；非 ASCII 与空段范围仍待核实。') }}</p>
          <p v-if="g.qid === 3451 && g.answer_evidence?.statement_revision" class="muted note">{{ t('新版官方题面明确每段包含 1 至 3 个数字；检查全部段的越界、前导零及段数，单个 0 合法。') }}</p>
          <p v-if="g.answer_evidence?.oracle_scope?.max_text_length" class="muted note">{{ t('文本核验范围：每行最多 {0} 个字符、每个输入合计最多 {1} 个字符，范围外合法输入仍待核实。', [g.answer_evidence.oracle_scope.max_text_length, g.answer_evidence.oracle_scope.max_total_text_length]) }}</p>
          <p v-if="g.answer_evidence?.statement_revision" class="muted note">{{ t('题面规则版本') }}：{{ g.answer_evidence.statement_revision.version }} · <a :href="g.answer_evidence.statement_revision.source.url" target="_blank" rel="noopener noreferrer">{{ t('官方规则来源') }}</a> · SHA {{ g.answer_evidence.statement_revision.source.official_html_sha256.slice(0,12) }}</p>
          <p v-if="g.answer_evidence?.execution_protocol" class="muted note">{{ t('执行协议') }}：{{ g.answer_evidence.execution_protocol.version }} · {{ t('回调使用已审查的声明式函数族，尚未验证任意 JavaScript 回调') }}<span v-if="g.answer_evidence.execution_protocol.clock"> · {{ t('异步执行使用确定性时钟与原生 Promise 微任务，未证明与 LC 墙钟时序完全等价') }}</span></p>
          <p v-if="g.answer_evidence?.limitations?.includes('equal_deadline_pending_verified_interpretation')" class="muted note">{{ t('timeLimit 恰好同时完成与超时的边界仍待核实，此类输入暂不自动发布') }}</p>
          <details v-if="g.source_code" class="note"><summary>{{ t('翻译源代码与来源') }} · {{ langLabel(g.source_language || '') }}</summary><p v-if="g.source_snapshot" class="muted">{{ g.source_snapshot.job_title }} · {{ g.source_snapshot.model_name }} · SHA {{ g.source_snapshot.code_sha256 }}</p><p v-if="g.source_snapshot?.input_contract" class="muted">{{ t('源输入输出契约已冻结') }} · SHA {{ g.source_snapshot.input_contract.sha256.slice(0,12) }}<span v-if="g.source_snapshot.input_contract.provenance === 'recovered_from_frozen_prompt'"> · {{ t('恢复自原始生成提示词') }}</span></p><p v-else-if="g.source_snapshot" class="muted">{{ t('历史源代码未保存结构化契约，兼容性需核对。') }}</p><pre class="code">{{ g.source_code }}</pre></details>
          <div class="metric-row">
            <!-- Behavioral metrics retain their original probe-only meaning. -->
            <div><span>{{ t("行为不确定性 U") }}</span><strong>{{ uncertainty(g.metrics?.uncertainty) }}</strong><small>{{ t("0 集中 · 1 分散") }}</small></div>
            <div><span>{{ g.corpus_count ? t("全部本地测试通过率") : g.corpus_evidence?.evidence_level === 'official_examples_only' ? t("公开示例验证通过率") : t("本地验证通过率") }}</span><strong>{{ pct(g.local_pass_rate) }}</strong><small>{{ g.corpus_count || g.validation_count }} {{ t("个测试输入") }}<span v-if="g.probe_selection?.private_validation_count != null"> {{ t("· 分离验证含补充") }} {{ g.probe_selection.private_validation_count }} {{ t("个") }}</span></small></div>
            <div><span>{{ t("两两行为一致率") }}</span><strong>{{ pct(g.metrics?.mean_pairwise_agreement) }}</strong><small>{{ t("仅在共享探测输入上比较") }}</small></div>
            <div><span>{{ t("已生成候选代码") }}</span><strong>{{ g.candidates.filter(c => c.code).length }} / {{ selected.spec.num_candidates }}</strong><small>{{ probeCount(g) || '—' }} {{ t("个探测输入") }}</small></div>
          </div>
          <p v-if="g.metrics?.reason" class="note">{{ t(g.metrics.reason) }}</p>
          <section v-if="g.selection_advice" class="selection-advice">
            <el-alert :type="g.selection_advice.state === 'recommended' ? 'success' : g.selection_advice.state === 'abstained' ? 'warning' : 'info'" :closable="false" :title="g.selection_advice.state === 'recommended' ? t('验证后建议：候选 {0}', [g.selection_advice.candidate_index]) : g.selection_advice.state === 'abstained' ? t('暂无可建议的候选') : t('选码依据尚不完整')" :description="t(g.selection_advice.reason)" />
            <p v-if="g.selection_advice.state === 'recommended'" class="note">{{ g.selection_advice.eligible_count }} {{ t("份候选满足筛选条件 · 建议候选通过") }} {{ g.selection_advice.validation_count }} {{ t("个本地验证输入。") }}<b v-if="!g.selection_advice.same_as_behavior_center">{{ t("已与原行为中心候选区分。") }}</b></p>
            <p class="muted note">{{ t(g.selection_advice.notice) }}<span v-if="g.selection_advice.provenance === 'derived_from_saved_evidence'"> {{ t("此建议根据历史证据临时计算，原始评测结果没有改写。") }}</span></p>
            <details v-if="advisedCandidate(g)"><summary>{{ t("查看建议候选") }} {{ g.selection_advice.candidate_index }} {{ t("的代码") }}</summary><pre class="code">{{ advisedCandidate(g)?.code }}</pre></details>
            <details v-if="g.selection_advice.rejected.length"><summary>{{ t("查看") }} {{ g.selection_advice.rejected.length }} {{ t("份候选未被建议的原因") }}</summary><p v-for="r in g.selection_advice.rejected" :key="r.candidate_id" class="note">{{ t("候选") }} {{ r.candidate_index }}：{{ r.reasons.map((reason: string) => t(reason)).join('; ') }}</p></details>
          </section>
          <p v-if="g.probe_selection" class="muted note">{{ g.probe_selection.strategy === 'balanced' ? t("覆盖优先") : t("输入哈希顺序") }} {{ t("· 请求") }} {{ g.probe_selection.requested_probe_count }} {{ t("/ 实际") }} {{ g.probe_selection.actual_probe_count }} {{ t("个探测输入 ·") }} {{ g.probe_selection.validation_count }} {{ t("个验证输入 · 已覆盖") }} {{ g.probe_selection.features_covered }}/{{ g.probe_selection.features_available }} {{ t("类可观察输入特征（不是完整测试覆盖率）") }}</p>
          <el-alert v-for="warning in g.probe_selection?.warnings || []" :key="warning" type="warning" :title="t(warning)" :closable="false" />
          <el-collapse>
            <el-collapse-item v-if="g.metrics?.matrix" :title='t("查看行为相似矩阵")' name="matrix">
              <p class="note">{{ t("行和列都是候选编号。1 表示全部探测行为一致，0 表示没有计入一致；小数表示一致输入所占比例。点击格子查看具体输入和两份输出。对角线固定为 1，不能用来判断正确性。") }}</p>
              <div class="matrix-scroll"><div class="matrix" :style="{ gridTemplateColumns: `repeat(${g.metrics.matrix.length + 1}, 48px)` }"><span aria-hidden="true">{{ t("行 / 列") }}</span><span v-for="(_, j) in g.metrics.matrix" :key="`col-${j}`">{{ j+1 }}</span><template v-for="(row, i) in g.metrics.matrix" :key="i"><span>{{ i+1 }}</span><button v-for="(cell, j) in row" :key="j" type="button" :aria-label="t('比较候选 {0} 与候选 {1}，相似度 {2}', [i+1, j+1, cell.toFixed(3)])" :title="t('候选 {0} / {1}：{2}', [i+1, j+1, cell.toFixed(3)])" :style="{ background: `rgba(79,110,247,${0.05 + cell * 0.85})`, color: cell > 0.6 ? 'white' : '#334155' }" @click="compareCell(g,i,j)">{{ Number(cell.toFixed(2)) }}</button></template></div></div>
            </el-collapse-item>
            <el-collapse-item v-for="c in g.candidates" :key="c.id" :name="c.id">
              <template #title><div class="candidate-heading"><span>{{ t("候选") }} {{ c.index }}</span><el-tag v-if="c.selected" size="small" type="info" class="candidate-tag">{{ t("行为中心候选") }}</el-tag><el-tag v-if="g.selection_advice?.candidate_id === c.id" size="small" type="success" class="candidate-tag">{{ t("验证后建议") }}</el-tag><el-tag v-if="c.corpus_verdict || (!fullExecution(g) && c.verdict)" size="small" :type="(c.corpus_passed ?? c.validation_passed) ? 'success' : 'danger'" class="candidate-tag">{{ (c.corpus_verdict || c.verdict)?.ac_status }}</el-tag><el-tag v-else-if="c.generation_state === 'failed'" size="small" type="danger" class="candidate-tag">{{ t("生成失败") }}</el-tag><span v-else class="muted candidate-tag">{{ active(selected.state) ? (c.generation_state === 'generating' ? t("生成中") : t("评测中")) : fullExecution(g) ? t('完整复判未完成') : t("评测未完成") }}</span></div></template>
              <p v-if="c.code_sha256" class="muted endpoint">{{ c.corpus_verdict?.runtime || c.verdict?.runtime }} · {{ c.corpus_verdict?.memory || c.verdict?.memory }} {{ t("· 源码 SHA256") }} {{ c.code_sha256 }}</p>
              <p v-if="c.translation_preservation != null">{{ t("转译行为保持率：") }}{{ pct(c.translation_preservation) }}</p>
              <el-button v-if="c.code && c.code_sha256 && (c.generation_state || 'succeeded') === 'succeeded' && c.finish_reason !== 'length'" size="small" @click="translateCandidate(g,c)">{{ t('翻译此代码') }}</el-button>
              <el-button v-if="c.code && c.code_sha256 && (c.generation_state || 'succeeded') === 'succeeded' && c.finish_reason !== 'length' && !active(selected.state)" size="small" type="primary" plain @click="rejudgeCandidate(g,c)">{{ t('原代码复判') }}</el-button>
              <el-alert v-if="c.judging_failure" type="error" :title="t(c.judging_failure.message)" :closable="false" />
              <el-alert v-if="c.finish_reason === 'length'" type="warning" :title='t("模型输出达到 token 上限，代码可能截断")' :closable="false" />
              <el-tabs><el-tab-pane :label='t("生成代码")'><pre v-if="c.code" class="code">{{ c.code }}</pre><p v-else class="muted note">{{ t("尚未生成代码，请查看调用诊断。") }}</p></el-tab-pane><el-tab-pane :label='t("原始返回")'><pre class="code">{{ c.raw }}</pre></el-tab-pane><el-tab-pane :label='t("调用诊断")'>
                <p v-if="c.generation_state === 'generating' && c.generation?.in_flight" class="note">{{ t("调用") }} {{ c.generation.in_flight.attempt }} · HTTP {{ c.generation.in_flight.http_status ?? t("等待响应") }} {{ t("· 已读取") }} {{ c.generation.in_flight.received_bytes }} {{ t("字节 · 已等待") }} {{ c.generation.in_flight.elapsed_seconds }}{{ t("s / 响应正文预算") }} {{ c.generation.in_flight.response_budget_seconds }}s。<span v-if="c.generation.in_flight.received_bytes && c.generation.in_flight.only_whitespace_so_far">{{ t("目前仅收到空白保活数据，尚未收到代码。") }}</span></p>
                <p v-if="!c.generation?.attempts?.length" class="muted note">{{ t("该候选没有详细调用记录。") }}</p>
                <el-collapse v-else><el-collapse-item v-for="a in c.generation.attempts" :key="a.attempt" :name="a.attempt" :title="t('调用 {0} · {1} · {2} ms', [a.attempt, t(a.message), a.duration_ms])">
                  <div class="diagnostic-meta"><span>HTTP：{{ a.http_status ?? t("未收到响应") }}</span><span>{{ t("停止原因：") }}{{ a.finish_reason || '—' }}</span><span>{{ t("代码字符：") }}{{ a.content_chars }}</span><span>{{ t("推理字符：") }}{{ a.reasoning_chars }}</span><span>{{ t("自动重试：") }}{{ a.retry_scheduled ? t("等待 {0}s", [a.retry_delay_seconds]) : t("否") }}</span></div>
                  <p class="note">{{ t(a.suggestion) }}</p><p class="muted endpoint">{{ a.request.model }} {{ t("· 温度") }} {{ a.request.temperature }} {{ t("· token 上限") }} {{ a.request.max_tokens }} · {{ a.request.endpoint }}</p>
                  <p class="muted endpoint">{{ t("实际思考参数：") }}{{ JSON.stringify(a.request.thinking_control || {}) }}</p>
                  <p class="muted endpoint">{{ t("token 用量：") }}{{ JSON.stringify(a.usage) }} {{ t("· 请求 ID：") }}{{ a.request_id || t("未提供") }}</p>
                  <p class="muted endpoint">{{ t("响应") }} {{ a.response_bytes }} {{ t("字节 · SHA256") }} {{ a.response_sha256 }}</p>
                  <el-alert v-if="a.response_capture_truncated || a.response_read_complete === false" type="warning" :title='t("响应或摘录未完整保存；哈希绑定本次读取的内容，不代表摘录包含完整响应")' :closable="false" />
                  <pre class="code">{{ a.response_body || t("没有收到响应正文") }}</pre>
                </el-collapse-item></el-collapse>
              </el-tab-pane><el-tab-pane :label='t("逐输入行为")'><el-table :data="c.outcomes"><el-table-column type="index" :label='t("输入")' width="70" /><el-table-column prop="kind" :label='t("行为")' width="130" ><template #default="{ row }">{{ t(row.kind) }}</template></el-table-column><el-table-column :label='t("输出 / 失败")'><template #default="{row}"><code>{{ outcomeText(row) }}</code></template></el-table-column><el-table-column prop="runtime_ms" :label='t("运行 ms")' width="110" /><el-table-column :label='t("编译 / 启动传输 ms")' min-width="160"><template #default="{row}"><span v-if="row.timing">{{ row.timing.compile_ms.toFixed(1) }} / {{ row.timing.startup_transport_ms.toFixed(1) }}<br /><small class="muted">{{ row.timing.cache_mode === 'warm' ? t("复用编译产物，重新执行") : row.timing.cache_mode === 'cold' ? t("首次编译并执行") : t("独立执行") }}</small></span><span v-else>{{ t("历史未记录") }}</span></template></el-table-column></el-table></el-tab-pane>
                <el-tab-pane v-if="c.metamorphic?.length" :label='t("变形关系")'><p class="muted note">{{ t("检查输入变换后的输出关系，提供风险线索；通过不代表代码正确，结果不参与 AC 或谱熵计算。") }}</p><el-collapse><el-collapse-item v-for="(r, ri) in c.metamorphic" :key="ri" :name="ri" :title="`${r.rule} · ${r.state === 'passed' ? t('关系满足') : r.state === 'violated' ? t('关系违反') : r.state === 'execution_failure' ? t('执行失败') : t('无法检查')}`"><p>{{ t("原探测输入") }} {{ r.base_probe_index + 1 }}</p><p v-if="r.reason">{{ t(r.reason) }}</p><pre class="code">{{ JSON.stringify({ transformed_input: r.input, original_output: r.base_outcome.value, relation_expected: r.relation_expected, transformed_output: r.outcome.value, status: r.outcome.status }, null, 2) }}</pre></el-collapse-item></el-collapse></el-tab-pane>
              </el-tabs>
            </el-collapse-item>
          </el-collapse>
        </el-card>
        <el-card v-if="selected.result?.cross_language?.length" shadow="never" class="group-card"><template #header>{{ t("跨语言输出一致性") }}</template><el-table :data="selected.result.cross_language"><el-table-column prop="qid" :label='t("题号")' /><el-table-column :label='t("模型")'><template #default="{row}">{{ modelLabel(row.model_id) }}</template></el-table-column><el-table-column :label='t("语言对")'><template #default="{row}">{{ langLabel(row.left) }} ↔ {{ langLabel(row.right) }}</template></el-table-column><el-table-column :label='t("一致率")'><template #default="{row}">{{ pct(row.agreement) }}</template></el-table-column></el-table></el-card>
      </template>
    </el-drawer>
    <el-dialog v-model="comparisonOpen" :title='t("行为矩阵 · 逐输入解释")' width="min(960px, 96vw)" append-to-body>
      <template #header="{ titleId, titleClass }"><div class="dialog-heading"><span :id="titleId" :class="titleClass">{{ t('行为矩阵 · 逐输入解释') }}</span><LanguageToggle /></div></template>
      <div v-loading="comparisonBusy" style="min-height:120px">
        <template v-if="comparison">
          <p class="note"><b>q{{ comparison.qid }} {{ t("· 候选") }} {{ comparison.left }} {{ t("↔ 候选") }} {{ comparison.right }}</b><br />{{ t("相似度") }} {{ comparison.similarity.toFixed(3) }} = {{ comparison.matches }} / {{ comparison.total }} {{ t("个探测输入计入一致。") }}</p>
          <el-alert :title="t(comparison.notice)" type="info" :closable="false" />
          <el-alert v-if="!comparison.inputs_available" :title='t("历史任务没有保存探测输入；可解释已记录行为，但无法补造原始输入。")' type="warning" :closable="false" />
          <el-switch v-model="onlyDifferences" :active-text='t("仅看差异")' /><span class="muted"> · {{ comparison.differing }} {{ t("个差异输入") }}</span>
          <el-empty v-if="!comparisonRows.length" :description='t("当前没有差异；关闭“仅看差异”查看全部输入")' />
          <article v-for="r in comparisonRows" :key="r.probe_index" class="comparison-row">
            <p><b>{{ t("探测输入") }} {{ r.probe_index }}</b> · {{ r.matched ? t("计入一致") : t("未计入一致") }} · {{ t(r.reason) }}</p>
            <details v-if="r.input"><summary>{{ t("输入预览（点击展开完整内容）") }}</summary><pre class="code">{{ pretty(r.input) }}</pre></details><pre v-if="r.input" class="comparison-preview">{{ preview(r.input) }}</pre>
            <div class="comparison-outputs"><div v-for="(o, oi) in [r.left, r.right]" :key="oi"><b>{{ t("候选") }} {{ oi === 0 ? comparison.left : comparison.right }} · {{ o.kind }}</b><pre class="comparison-preview">{{ o.kind === 'value' ? preview(o.value) : o.exception_type || o.status }}</pre><details><summary>{{ t("完整输出与状态") }}</summary><pre class="code">{{ pretty(o) }}</pre></details></div></div>
          </article>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.dialog-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-right:20px; min-width:0 }
.dialog-heading>span { overflow-wrap:anywhere }
.lab-intro { display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:22px }
.mobile-list { display:none }
.mobile-record { border:1px solid #e2e8f0; border-radius:8px; padding:14px; min-width:0 }
.mobile-record p { font-size:13px; margin:6px 0 }
.record-title { display:flex; justify-content:space-between; align-items:flex-start; gap:12px }
.record-title b { font-size:14px; overflow-wrap:anywhere }
.record-actions { display:flex; flex-wrap:wrap; gap:14px; margin-top:14px }
.record-actions :deep(.el-button+.el-button) { margin-left:0 }
.endpoint { overflow-wrap:anywhere }
.diagnostic-meta { display:flex; flex-wrap:wrap; gap:8px 18px; font-size:13px; color:#64748b }
.lab-intro h2 { font-size:23px; margin-bottom:6px }
.lab-intro p,.muted { color:#64748b; font-size:13px }
.toolbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:16px }
.form-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px }
.triple { grid-template-columns:1fr 1fr 1fr }
.note { margin:12px 0; font-size:13px; line-height:1.7 }
.group-card { margin-top:20px }
.metric-row { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px }
.metric-row>div { background:#f6f8fc; padding:15px; border-radius:8px }
.metric-row span,.metric-row small { display:block; font-size:12px; color:#64748b }
.metric-row strong { display:block; font-size:27px; margin:6px 0; color:#334155 }
.candidate-tag { margin-left:12px }
.candidate-heading { display:flex; flex:1; min-width:0; align-items:center; flex-wrap:wrap; gap:6px 10px; line-height:1.6; padding:8px 0 }
.candidate-heading .candidate-tag { margin-left:0 }
.group-card :deep(.el-collapse-item__header) { height:auto; min-height:48px }
.selection-advice { padding:14px; background:#f6f8fc; border-radius:8px; margin:16px 0 }
.selection-advice summary { cursor:pointer; font-size:13px; color:#4f6ef7; margin:10px 0 }
.matrix-scroll { overflow-x:auto }
.matrix { display:grid; gap:3px; width:max-content; margin:12px 0 }
.matrix button,.matrix span { height:44px; display:flex; align-items:center; justify-content:center; font-size:12px; border-radius:4px; border:0 }
.matrix button { cursor:pointer; font-family:inherit }
.matrix button:focus-visible { outline:3px solid #1d4ed8; outline-offset:1px }
.comparison-row { margin-top:18px; padding:14px; border:1px solid #e2e8f0; border-radius:8px }
.comparison-row p { font-size:13px; line-height:1.7 }
.comparison-row summary { cursor:pointer; font-size:13px; color:#4f6ef7; margin:10px 0 }
.comparison-outputs { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px }
.comparison-preview { font:12px/1.6 Consolas,monospace; padding:10px; background:#f6f8fc; white-space:pre-wrap; overflow-wrap:anywhere; max-height:180px; overflow:auto }
.code { white-space:pre-wrap; overflow-wrap:anywhere; background:#111827; color:#e2e8f0; padding:20px; border-radius:8px; font:13px/1.6 Consolas,monospace; max-height:550px; overflow:auto }
.catalog-summary {display:flex;flex-wrap:wrap;gap:12px 28px;padding:16px 20px;background:var(--color-bg-card, #fff);border:1px solid var(--color-border, #e5e7eb);border-radius:10px;margin-bottom:16px}
.catalog-summary b {font-size:22px;color:var(--color-primary);margin:0 4px}
.question-evidence {display:flex;flex-wrap:wrap;gap:4px 14px;margin:-2px 0 12px;color:var(--color-text-secondary, #64748b);font-size:13px}
:deep(.el-pagination) {margin-top:18px;justify-content:center}
:deep(.el-alert) { margin-bottom:14px }
@media(max-width:1100px) { .metric-row {grid-template-columns:1fr 1fr} }
@media(max-width:900px) {
  .comparison-outputs { grid-template-columns:1fr }
  .desktop-table { display:none }
  .mobile-list { display:grid; gap:12px }
  .lab-intro { flex-direction:column; align-items:flex-start }
  .lab-intro h2 { font-size:20px }
  .form-grid,.triple { grid-template-columns:1fr }
}
</style>
