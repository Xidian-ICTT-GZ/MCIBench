<script setup lang="ts">
import { t } from '@/i18n'
import LanguageToggle from '@/components/LanguageToggle.vue'

import { computed, ref } from 'vue'

const languages = ['Python', 'C', 'C++', 'C#', 'Java', 'JavaScript', 'Go', 'Rust']
const features = computed(() => [
  { number: '01', title: t("同题八语，语义可比"), description: t("围绕同一道题、同一语义目标，比较八种语言的生成结果。既看各自是否通过，也看跨语言执行行为是否一致。"), paths: ['M4 5h7M7 3v2c0 5-2 8-5 10', 'M4 9c1 3 3 5 6 6', 'm12 21 5-12 5 12M14 17h6'] },
  { number: '02', title: t("本地沙箱，隔离执行"), description: t("代码在受限的本地容器中编译、运行与验证，区分答案错误、编译失败、异常和超时，让评价落到真实执行。"), paths: ['m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7l8-4Z', 'm8 12 3 3 5-6'] },
  { number: '03', title: t("生成转译，一体评测"), description: t("从题面生成代码，或从源语言参考程序定向转译。在相同输入上比较目标实现，并观察转译后的行为保持情况。"), paths: ['M4 7h15m-4-4 4 4-4 4', 'M20 17H5m4-4-4 4 4 4'] },
  { number: '04', title: t("行为共识，观察风险"), description: t("借鉴 Code-MUE，用多候选执行相似图与谱熵衡量行为分歧。普通输出比较无需逐例标准答案，为正确性验证补充风险信号。"), paths: ['M6 6 12 12 18 5M12 12l6 7M6 18l6-6', 'M6 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6M18 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6M18 16a3 3 0 1 0 0 6 3 3 0 0 0 0-6'] },
  { number: '05', title: t("差异分流，定位失因"), description: t("对照历史 LeetCode 判定，将漏检与误拒分开分析。结合题目、语言和模型定位覆盖缺口、输入约束及判题环境差异。"), paths: ['M6 3v12a3 3 0 0 0 3 3h9', 'M6 8h9a3 3 0 0 1 3 3v7', 'm15 15 3 3-3 3'] },
  { number: '06', title: t("全程留痕，结果可查"), description: t("保留任务参数、提示词、候选源码、输入和版本指纹。支持任务复制与 JSON 导出，让结论能够回到具体代码和执行证据。"), paths: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z', 'M14 2v6h6M8 13h8M8 17h5'] },
])
const steps = computed(() => [
  { title: t("选择评测对象"), description: t("选择现有题目、模型和目标语言，设定候选数、探测输入数与采样温度。"), tag: t("题目 × 模型 × 语言") },
  { title: t("生成或定向转译"), description: t("从题面生成多份候选，或提供源语言参考程序，生成目标语言实现。"), tag: t("多次采样 · 两类任务") },
  { title: t("执行与双重观察"), description: t("共享探测输入比较行为，另用不重叠的验证输入检查正确性。"), tag: t("行为稳定性 + 本地验证") },
  { title: t("分析并回看证据"), description: t("查看判定、谱熵、相似矩阵和跨语言一致率，回看源码并导出结果。"), tag: t("指标 → 候选 → 执行记录") },
])
const scenarios = computed(() => [
  { id: 'correct', title: t("一致且通过"), uncertainty: '0.000', accepted: '5 / 5', split: false, explanation: t("五份候选在探测输入上行为相同，也都通过独立验证。当前证据同时支持行为稳定与本地正确。") },
  { id: 'wrong', title: t("一致但失败"), uncertainty: '0.000', accepted: '0 / 5', split: false, explanation: t("五份候选可能犯了同一个错误。行为完全一致，谱熵仍为零，但独立验证揭示了共同错误。") },
  { id: 'split', title: t("行为分成两组"), uncertainty: '0.418', accepted: '3 / 5', split: true, explanation: t("三份候选与另外两份候选形成不同的行为组。谱熵反映这种分歧；谁正确，需要另看验证证据。") },
] as const)
const selectedScenario = ref<'correct' | 'wrong' | 'split'>('split')
const scenario = computed(() => scenarios.value.find(item => item.id === selectedScenario.value)!)
const matrixCells = computed(() => Array.from({ length: 25 }, (_, index) => {
  const row = Math.floor(index / 5)
  const column = index % 5
  return { row, column, same: !scenario.value.split || (row < 3) === (column < 3) }
}))
</script>

<template>
  <div class="cover-page">
    <a class="skip-link" href="#cover-main">{{ t("跳到主要内容") }}</a>
    <header class="cover-header">
      <div class="cover-container cover-header-inner">
        <router-link to="/" class="cover-brand" :aria-label='t("MCIBench 平台介绍")'>
          <span class="cover-logo-icon" aria-hidden="true">L</span>
          <span>MCIBench<span class="brand-caption">{{ t("多语言代码质量评测") }}</span></span>
        </router-link>
        <nav class="cover-nav" :aria-label='t("平台介绍导航")'>
          <a href="#features">{{ t("平台特色") }}</a><a href="#workflow">{{ t("评测流程") }}</a><a href="#behavior">{{ t("行为评估") }}</a>
        </nav>
        <div class="cover-header-actions"><LanguageToggle /><router-link to="/lab" class="cover-button cover-button-small">{{ t("进入平台") }} <span aria-hidden="true">↗</span></router-link></div>
      </div>
    </header>

    <main id="cover-main">
      <section class="cover-hero" aria-labelledby="hero-title">
        <div class="cover-container hero-grid">
          <div class="hero-copy">
            <div class="eyebrow"><span class="status-dot" /> {{ t("平台概览") }}</div>
            <p class="hero-product">MCIBench <span>{{ t("评测原型系统") }}</span></p>
            <h1 id="hero-title">{{ t("让代码能力，") }}<br />{{ t("在执行中") }}<span>{{ t("被看见。") }}</span></h1>
            <p class="hero-description">{{ t("连接代码生成、定向转译、本地验证与行为不确定性，") }}<br class="desktop-break" />{{ t("观察大模型在不同语言中的正确性、一致性与潜在风险。") }}</p>
            <div class="hero-actions">
              <router-link to="/lab" class="cover-button">{{ t("开始评测") }} <span aria-hidden="true">↗</span></router-link>
              <router-link to="/dashboard" class="cover-button cover-button-outline">{{ t("查看评测总览") }} <span aria-hidden="true">→</span></router-link>
            </div>
            <p class="hero-note">{{ t("同一问题 · 多种语言 · 可检查的执行证据") }}</p>
          </div>

          <div class="hero-visual">
            <div class="visual-heading"><span>{{ t("代码 · 行为 · 评测证据") }}</span><span class="visual-pill">{{ t("方法示意") }}</span></div>
            <div class="language-stack" :aria-label='t("八种目标语言")'>
              <span v-for="language in languages" :key="language">{{ language }}</span>
            </div>
            <svg class="behavior-graph" viewBox="0 0 500 305" role="img" aria-labelledby="graph-title graph-description">
              <title id="graph-title">{{ t("多候选代码的执行行为相似图示意") }}</title>
              <desc id="graph-description">{{ t("同题多次生成的五份代码，在共享输入上形成两个行为组，再分别观察行为不确定性和本地验证。") }}</desc>
              <defs><pattern id="cover-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="var(--border-color)" /></pattern></defs>
              <rect width="500" height="305" fill="url(#cover-grid)" />
              <text x="24" y="28" class="graph-small">{{ t("共享探测输入") }}</text>
              <rect x="24" y="42" width="138" height="34" rx="7" fill="#fff" stroke="#d4dfed" />
              <text x="93" y="64" text-anchor="middle" class="graph-mono">x₁, x₂, …, xₖ</text>
              <path d="M163 59h37m-5-4 5 4-5 4" stroke="#9ab0cd" fill="none" />
              <path d="M232 95 307 150 216 202Z" fill="var(--color-primary-light)" stroke="var(--color-primary)" stroke-width="2" />
              <path d="m394 94 20 108" stroke="var(--color-success)" stroke-width="2" />
              <path d="m307 150 87-56m-87 56 107 52" stroke="#aab9ce" stroke-dasharray="5 5" />
              <circle cx="232" cy="95" r="22" fill="#fff" stroke="var(--color-primary)" stroke-width="2" /><text x="232" y="100" text-anchor="middle" class="graph-label">C₁</text>
              <circle cx="307" cy="150" r="22" fill="#fff" stroke="var(--color-primary)" stroke-width="2" /><text x="307" y="155" text-anchor="middle" class="graph-label">C₂</text>
              <circle cx="216" cy="202" r="22" fill="#fff" stroke="var(--color-primary)" stroke-width="2" /><text x="216" y="207" text-anchor="middle" class="graph-label">C₃</text>
              <circle cx="394" cy="94" r="22" fill="#fff" stroke="var(--color-success)" stroke-width="2" /><text x="394" y="99" text-anchor="middle" class="graph-label">C₄</text>
              <circle cx="414" cy="202" r="22" fill="#fff" stroke="var(--color-success)" stroke-width="2" /><text x="414" y="207" text-anchor="middle" class="graph-label">C₅</text>
              <text x="225" y="254" text-anchor="middle" class="graph-small">{{ t("行为组 A") }}</text><text x="408" y="254" text-anchor="middle" class="graph-small">{{ t("行为组 B") }}</text>
              <text x="24" y="289" class="graph-small">{{ t("比较功能行为，而非源码长得像不像。") }}</text>
            </svg>
            <div class="visual-evidence"><div><span class="evidence-dot blue" /><span>{{ t("行为不确定性") }}<small>{{ t("观察候选是否稳定") }}</small></span></div><div><span class="evidence-dot green" /><span>{{ t("独立本地验证") }}<small>{{ t("检查测试是否通过") }}</small></span></div></div>
          </div>
        </div>
        <div class="cover-container hero-bottom"><span>{{ t("生成 · 转译 · 验证") }}</span><a href="#features">{{ t("了解平台") }} <span aria-hidden="true">↓</span></a><span>{{ t("基于执行证据的质量评估") }}</span></div>
      </section>

      <section class="scope-bar" :aria-label='t("平台评测范围")'>
        <div class="cover-container scope-grid">
          <div><strong>8<span>{{ t("种语言") }}</span></strong><p>{{ t("同题多语言执行") }}</p></div>
          <div><strong class="scope-text">{{ t("可扩展题库") }}</strong><p>{{ t("历史 100 题 + 经门禁验证的新题") }}</p></div>
          <div><strong>2<span>{{ t("类任务") }}</span></strong><p>{{ t("代码生成与定向转译") }}</p></div>
          <div><strong class="scope-text">{{ t("双重观察") }}</strong><p>{{ t("正确性与行为稳定性") }}</p></div>
        </div>
      </section>

      <section id="features" class="cover-section" aria-labelledby="features-title">
        <div class="cover-container">
          <div class="section-heading"><div class="eyebrow">{{ t("平台特色") }}</div><h2 id="features-title">{{ t("从一个通过率，") }}<br />{{ t("走向一组可解释的证据。") }}</h2><p>{{ t("把同题比较、真实执行与行为分析连接起来，") }}<br class="desktop-break" />{{ t("让模型能力的差异有出处，生成代码的风险有线索。") }}</p></div>
          <div class="feature-grid">
            <article v-for="feature in features" :key="feature.number" class="feature-card">
              <div class="feature-top"><svg viewBox="0 0 24 24" aria-hidden="true"><path v-for="path in feature.paths" :key="path" :d="path" /></svg><span>{{ feature.number }}</span></div>
              <h3>{{ feature.title }}</h3><p>{{ feature.description }}</p>
            </article>
          </div>
        </div>
      </section>

      <section id="workflow" class="cover-section workflow-section" aria-labelledby="workflow-title">
        <div class="cover-container">
          <div class="section-heading"><div class="eyebrow">{{ t("主要流程") }}</div><h2 id="workflow-title">{{ t("选题到结果，") }}<br />{{ t("每一步都清晰可见。") }}</h2><p>{{ t("配置一次任务，串起生成、执行、评估与证据回看。") }}</p></div>
          <ol class="workflow-grid">
            <li v-for="(step, index) in steps" :key="step.title"><div class="step-number">0{{ index + 1 }}<span v-if="index < steps.length - 1" aria-hidden="true">→</span></div><h3>{{ step.title }}</h3><p>{{ step.description }}</p><span class="step-tag">{{ step.tag }}</span></li>
          </ol>
          <div class="workflow-tools"><span>{{ t("工作台功能") }}</span><ul><li>{{ t("模型配置增删改查") }}</li><li>{{ t("评测任务管理") }}</li><li>{{ t("现有题库选题") }}</li><li>{{ t("候选源码与结果导出") }}</li></ul></div>
        </div>
      </section>

      <section id="behavior" class="cover-section behavior-section" aria-labelledby="behavior-title">
        <div class="cover-container behavior-grid">
          <div class="behavior-copy"><div class="eyebrow">{{ t("行为质量评估 · Code-MUE") }}</div><h2 id="behavior-title">{{ t("从“答得对不对”，") }}<br />{{ t("到“生成得稳不稳”。") }}</h2><p class="behavior-lead">{{ t("减少对逐例标准答案的依赖，") }}<br />{{ t("从代码之间的行为分歧观察风险。") }}</p><p>{{ t("同题多次采样，让候选执行共享探测输入，建立行为相似图，用谱熵 U 衡量分散程度，并选出行为中心候选。普通返回值的相似度计算无需预先给出正确答案。") }}</p><div class="behavior-boundary"><strong>{{ t("稳定性与正确性，分别给证据。") }}</strong><p>{{ t("仍需合法探测输入与实际执行。低 U 不保证正确；多解题会使用题目规格进行比较。本地通过也不保证 LeetCode 通过。") }}</p></div><router-link to="/lab" class="text-link">{{ t("在评测任务中查看行为指标") }} <span aria-hidden="true">↗</span></router-link></div>
          <div class="behavior-demo">
            <div class="demo-heading"><span>{{ t("行为相似矩阵") }}</span><span>{{ t("机制示意 · 非真实结果") }}</span></div>
            <div class="scenario-controls" role="group" :aria-label='t("选择行为示例")'><button v-for="item in scenarios" :key="item.id" type="button" :aria-pressed="selectedScenario === item.id" :class="{ selected: selectedScenario === item.id }" @click="selectedScenario = item.id">{{ item.title }}</button></div>
            <div class="demo-body"><svg class="demo-matrix" viewBox="0 0 280 267" role="img" :aria-label="scenario.split ? t('五个候选形成三份和两份两个行为组的相似矩阵') : t('五个候选行为完全一致的相似矩阵')">
              <g v-for="index in 5" :key="index"><text :x="67 + (index - 1) * 43" y="25" text-anchor="middle" fill="var(--text-secondary)">C{{ index }}</text><text x="21" :y="62 + (index - 1) * 43" text-anchor="middle" fill="var(--text-secondary)">C{{ index }}</text></g>
              <g v-for="cell in matrixCells" :key="`${cell.row}-${cell.column}`"><rect :x="47 + cell.column * 43" :y="38 + cell.row * 43" width="38" height="38" rx="5" :fill="cell.same ? 'var(--color-primary)' : 'var(--color-primary-light)'" /><text :x="66 + cell.column * 43" :y="62 + cell.row * 43" text-anchor="middle" :fill="cell.same ? 'white' : 'var(--text-secondary)'">{{ cell.same ? '1' : '0' }}</text></g>
            </svg><div class="demo-metrics"><div><span>{{ t("行为不确定性 U") }}</span><strong>{{ scenario.uncertainty }}</strong><small>{{ t("0 集中 · 1 分散") }}</small></div><div><span>{{ t("验证通过候选") }}</span><strong :class="{ 'failed-count': selectedScenario === 'wrong' }">{{ scenario.accepted }}</strong><small>{{ t("来自另一组验证输入") }}</small></div></div></div>
            <p class="demo-explanation" aria-live="polite">{{ scenario.explanation }}</p>
          </div>
        </div>
      </section>

      <section class="cover-section evidence-section" aria-labelledby="evidence-title">
        <div class="cover-container evidence-grid"><div class="section-heading"><div class="eyebrow">{{ t("评价维度") }}</div><h2 id="evidence-title">{{ t("结论有层次，") }}<br />{{ t("判断有依据。") }}</h2><p>{{ t("一次评测，从不同角度读懂代码表现。") }}</p><router-link to="/agreement" class="text-link">{{ t("查看历史判题一致性") }} <span aria-hidden="true">↗</span></router-link></div><dl class="evidence-list"><div><dt>{{ t("功能正确性") }}</dt><dd>{{ t("本地判定与验证通过率，说明代码在现有验证输入上的表现。") }}</dd></div><div><dt>{{ t("语言一致性") }}</dt><dd>{{ t("同题不同语言的成功输出对比，观察语义是否保持一致。") }}</dd></div><div><dt>{{ t("采样稳定性") }}</dt><dd>{{ t("多候选谱熵与行为相似矩阵，观察重复生成的行为分歧。") }}</dd></div><div><dt>{{ t("转译保持性") }}</dt><dd>{{ t("目标代码与源参考程序的行为对比，观察转译是否保持功能。") }}</dd></div><div><dt>{{ t("失因与执行记录") }}</dt><dd>{{ t("查看编译、异常、超时及探测耗时，回到候选源码定位问题。") }}</dd></div></dl></div>
      </section>

      <section class="cover-section faq-section" aria-labelledby="faq-title"><div class="cover-container faq-grid"><div class="section-heading"><div class="eyebrow">{{ t("使用说明") }}</div><h2 id="faq-title">{{ t("开始之前，") }}<br />{{ t("了解评价的边界。") }}</h2></div><div class="faq-list"><details><summary>{{ t("行为评估可以完全不使用测试输入吗？") }}<span aria-hidden="true">+</span></summary><p>{{ t("不能。Code-MUE 的核心仍是执行比较，需要共享的合法探测输入；减少的是对逐例标准答案的依赖。当前平台从现有语料划分探测集与验证集，多解题还会使用规格信息。") }}</p></details><details><summary>{{ t("低不确定性或本地 Accepted，意味着一定正确吗？") }}<span aria-hidden="true">+</span></summary><p>{{ t("低不确定性只说明候选在当前探测输入上行为集中，所有候选可能共同犯错。本地 Accepted 说明通过现有验证输入，不能保证所有合法输入或 LeetCode 隐藏测试均通过。") }}</p></details><details><summary>{{ t("能使用哪些模型和语言？") }}<span aria-hidden="true">+</span></summary><p>{{ t("在模型配置中接入兼容 chat/completions 的模型服务，再创建任务。平台支持 Python、C、C++、C#、Java、JavaScript、Go 与 Rust，使用现有题库进行代码生成或定向转译。") }}</p></details><details><summary>{{ t("本地执行是否意味着整个过程都离线？") }}<span aria-hidden="true">+</span></summary><p>{{ t("代码编译与测试在本地沙箱中完成。生成阶段由你配置的模型服务提供；使用远程 API 时会发送生成提示及转译所需源码，使用本机模型服务时可在本地完成生成。") }}</p></details></div></div></section>

      <section class="cover-cta"><div class="cover-container cta-inner"><div class="eyebrow">{{ t("开始使用") }}</div><h2>{{ t("从一道题开始，") }}<br />{{ t("看见模型的代码能力。") }}</h2><p>{{ t("选择题目、模型与语言，开始一次有执行证据的评测。") }}</p><div class="hero-actions"><router-link to="/lab" class="cover-button">{{ t("进入评测平台") }} <span aria-hidden="true">↗</span></router-link><router-link to="/problems" class="cover-button cover-button-outline">{{ t("浏览题目与语料") }} <span aria-hidden="true">→</span></router-link></div></div></section>
    </main>
    <footer class="cover-footer"><div class="cover-container footer-inner"><span><strong>MCIBench</strong><span>{{ t("多语言代码质量评测原型系统") }}</span></span><span>{{ t("同题比较 · 行为观察 · 证据追溯") }}</span><a href="#cover-main">{{ t("返回顶部 ↑") }}</a></div></footer>
  </div>
</template>

<style scoped>
.cover-page {
  --cover-blue: var(--color-primary);
  --cover-ink: var(--text-primary);
  --cover-muted: var(--text-secondary);
  --cover-border: var(--border-color);
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: inherit;
}
.cover-page a { text-decoration: none; }
.cover-header-actions { display:flex; align-items:center; gap:12px; flex-shrink:0 }
.cover-page a, .cover-page button, .cover-page summary { -webkit-tap-highlight-color: transparent; }
.cover-page a:focus-visible, .cover-page button:focus-visible, .cover-page summary:focus-visible { outline: 3px solid var(--color-primary); outline-offset: 3px; }
.cover-container { width: min(1280px, calc(100% - 48px)); margin: 0 auto; }
.skip-link { position: fixed; top: -80px; left: 20px; z-index: 500; background: var(--bg-card); padding: 12px 20px; color: var(--cover-blue); }
.skip-link:focus { top: 12px; }
.cover-header { height: 64px; position: sticky; top: 0; background: var(--bg-card); z-index: 110; border-bottom: 1px solid var(--cover-border); }
.cover-header-inner { display: flex; align-items: center; justify-content: space-between; height: 100%; gap: 24px; }
.cover-brand { display: flex; gap: 10px; align-items: center; color: var(--cover-ink); font-size: 16px; font-weight: 700; }
.cover-logo-icon { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; background: linear-gradient(135deg, var(--color-primary), #8b5cf6); border-radius: 10px; color: #fff; font-size: 18px; font-weight: 800; flex-shrink: 0; }
.brand-caption { display: block; font-size: 10px; font-weight: 400; color: var(--cover-muted); }
.cover-nav { display: flex; gap: 28px; }
.cover-nav a { color: var(--cover-muted); font-size: 14px; }
.cover-nav a:hover, .text-link:hover { color: var(--cover-blue); }
.cover-button { display: inline-flex; justify-content: center; align-items: center; gap: 12px; min-height: 40px; padding: 10px 18px; color: var(--el-color-white); background: var(--el-color-primary); border: 1px solid var(--el-color-primary); border-radius: var(--el-border-radius-base); font-size: 14px; font-weight: 500; line-height: 1; transition: background .2s, border-color .2s; }
.cover-button:hover { background: var(--el-color-primary-light-3); border-color: var(--el-color-primary-light-3); }
.cover-button-small { min-height: 32px; padding: 8px 14px; }
.cover-button-outline { background: var(--bg-card); color: var(--el-text-color-regular); border-color: var(--el-border-color); }
.cover-button-outline:hover { background: var(--el-color-primary-light-9); color: var(--el-color-primary); border-color: var(--el-color-primary-light-7); }
.cover-hero { padding-top: 24px; }
.hero-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; align-items: center; padding: 28px; background: var(--bg-card); border: 1px solid var(--cover-border); border-radius: 12px; }
.eyebrow { color: var(--cover-blue); font-size: 12px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--color-success); }
.hero-product { color: var(--cover-ink); font-size: 20px; font-weight: 700; margin-top: 15px; }
.hero-product span { display: inline-block; color: var(--cover-muted); background: var(--bg-page); border: 1px solid var(--cover-border); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 400; margin-left: 10px; vertical-align: middle; }
.hero-copy h1 { font-size: 32px; line-height: 1.5; font-weight: 700; margin: 16px 0; }
.hero-copy h1 span { color: var(--cover-blue); }
.hero-description { color: var(--cover-muted); font-size: 14px; line-height: 1.9; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 22px; }
.hero-note { color: var(--text-muted); font-size: 12px; margin-top: 16px; }
.hero-visual { border: 1px solid var(--cover-border); border-radius: 8px; background: #f6f8fc; overflow: hidden; }
.visual-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px 12px; color: var(--cover-muted); font-size: 13px; }
.visual-pill { background: var(--color-primary-light); border: 1px solid #d9e0fd; color: var(--cover-blue); font-size: 11px; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
.language-stack { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 18px 12px; }
.language-stack span { font-size: 11px; border: 1px solid var(--cover-border); border-radius: 4px; background: var(--bg-card); color: var(--cover-muted); padding: 3px 7px; }
.behavior-graph { display: block; width: 100%; max-height: 250px; }
.graph-small { fill: var(--cover-muted); font-size: 11px; }
.graph-mono { fill: var(--cover-ink); font-size: 13px; font-family: Consolas, monospace; }
.graph-label { fill: var(--cover-ink); font: 15px Consolas, monospace; }
.visual-evidence { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--cover-border); background: var(--bg-card); }
.visual-evidence > div { display: flex; gap: 10px; padding: 12px 18px; font-size: 12px; }
.visual-evidence > div + div { border-left: 1px solid var(--cover-border); }
.visual-evidence small { display: block; color: var(--cover-muted); font-size: 11px; margin-top: 4px; }
.evidence-dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 7px; flex-shrink: 0; }
.evidence-dot.blue { background: var(--cover-blue); }
.evidence-dot.green { background: var(--color-success); }
.hero-bottom { display: flex; justify-content: space-between; align-items: center; padding: 14px 4px 0; color: var(--text-muted); font-size: 11px; }
.hero-bottom a { color: var(--cover-muted); font-size: 12px; }
.hero-bottom a span { padding-left: 8px; }
.scope-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 20px 0 0; }
.scope-grid > div { padding: 20px 24px; background: var(--bg-card); border: 1px solid var(--cover-border); border-radius: 12px; }
.scope-grid strong { font-size: 28px; font-weight: 700; line-height: 1.3; }
.scope-grid strong span { font-size: 13px; margin-left: 10px; font-weight: 400; color: var(--cover-muted); }
.scope-grid .scope-text { font-size: 23px; }
.scope-grid p { font-size: 12px; color: var(--cover-muted); margin-top: 6px; }
.cover-section { padding: 36px 0 0; scroll-margin-top: 82px; }
.section-heading h2, .behavior-copy h2, .cover-cta h2 { font-size: 23px; line-height: 1.5; font-weight: 700; margin: 10px 0; }
.section-heading h2 br, .cover-cta h2 br { display: none; }
.section-heading > p { color: var(--cover-muted); font-size: 13px; line-height: 1.8; }
.feature-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 20px; }
.feature-card { border: 1px solid var(--cover-border); border-radius: 12px; padding: 24px; background: var(--bg-card); }
.feature-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.feature-top svg { width: 42px; height: 42px; padding: 10px; background: var(--color-primary-light); border-radius: 10px; fill: none; stroke: var(--cover-blue); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.feature-top span { color: var(--text-muted); font-size: 12px; }
.feature-card h3 { font-size: 16px; font-weight: 600; }
.feature-card p { font-size: 13px; color: var(--cover-muted); line-height: 1.8; margin-top: 10px; }
.workflow-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; list-style: none; margin-top: 20px; }
.workflow-grid li { border: 1px solid var(--cover-border); border-radius: 12px; background: var(--bg-card); padding: 20px; }
.step-number { font-size: 23px; font-weight: 700; color: var(--cover-blue); padding-bottom: 12px; border-bottom: 1px solid var(--cover-border); display: flex; justify-content: space-between; }
.step-number span { font-size: 18px; color: var(--text-muted); }
.workflow-grid h3 { margin: 15px 0 9px; font-size: 15px; font-weight: 600; }
.workflow-grid p { font-size: 13px; color: var(--cover-muted); line-height: 1.8; }
.step-tag { display: inline-block; margin-top: 14px; color: var(--cover-blue); background: var(--color-primary-light); border-radius: 4px; padding: 3px 6px; font-size: 11px; }
.workflow-tools { margin-top: 16px; padding: 16px 20px; border: 1px solid var(--cover-border); border-radius: 8px; background: var(--bg-card); display: flex; align-items: baseline; gap: 24px; font-size: 12px; color: var(--cover-muted); }
.workflow-tools > span { color: var(--cover-ink); white-space: nowrap; font-weight: 600; }
.workflow-tools ul { display: flex; flex-wrap: wrap; gap: 10px 24px; list-style: none; }
.behavior-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: stretch; }
.behavior-copy, .behavior-demo { border: 1px solid var(--cover-border); border-radius: 12px; padding: 24px; background: var(--bg-card); }
.behavior-copy h2 { margin: 12px 0; }
.behavior-lead { font-size: 14px; color: var(--cover-blue); line-height: 1.8; margin-bottom: 14px; }
.behavior-copy > p:not(.behavior-lead) { color: var(--cover-muted); font-size: 13px; line-height: 1.8; }
.behavior-boundary { margin: 18px 0 0; padding: 12px 14px; border-radius: 8px; background: var(--color-primary-light); border-left: 3px solid var(--cover-blue); }
.behavior-boundary strong { color: var(--cover-ink); font-size: 13px; font-weight: 600; }
.behavior-boundary p { color: var(--cover-muted); font-size: 12px; line-height: 1.8; margin-top: 5px; }
.text-link { display: inline-flex; gap: 10px; font-size: 13px; color: var(--el-color-primary); margin-top: 18px; }
.demo-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 14px; font-weight: 600; }
.demo-heading span:last-child { font-size: 11px; font-weight: 400; color: var(--cover-muted); background: var(--bg-page); border-radius: 4px; padding: 3px 6px; }
.scenario-controls { display: flex; gap: 0; margin: 18px 0; border: 1px solid var(--cover-border); border-radius: 6px; overflow: hidden; }
.scenario-controls button { flex: 1; background: var(--bg-card); border: none; border-right: 1px solid var(--cover-border); color: var(--cover-muted); font: inherit; font-size: 12px; padding: 8px 4px; cursor: pointer; }
.scenario-controls button:last-child { border-right: none; }
.scenario-controls button.selected { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.scenario-controls button:focus-visible { outline-offset: -3px; }
.demo-body { display: grid; grid-template-columns: 1.5fr 1fr; gap: 20px; align-items: center; }
.demo-matrix { width: 100%; max-width: 280px; display: block; margin: 0 auto; }
.demo-matrix text { font: 12px Consolas, monospace; }
.demo-metrics { display: flex; flex-direction: column; gap: 14px; }
.demo-metrics > div { background: #f6f8fc; padding: 14px; border-radius: 8px; }
.demo-metrics span, .demo-metrics small { font-size: 12px; color: #64748b; display: block; }
.demo-metrics strong { display: block; font-size: 27px; font-weight: 700; color: #334155; margin: 6px 0; }
.demo-metrics strong.failed-count { color: var(--color-danger); }
.demo-metrics small { font-size: 11px; }
.demo-explanation { border-top: 1px solid var(--cover-border); margin-top: 18px; padding-top: 14px; font-size: 13px; line-height: 1.8; color: var(--cover-muted); }
.evidence-grid { display: grid; grid-template-columns: 1fr 1.35fr; gap: 32px; background: var(--bg-card); border: 1px solid var(--cover-border); border-radius: 12px; padding: 24px; }
.evidence-list > div { display: grid; grid-template-columns: 110px 1fr; gap: 20px; padding: 13px 0; border-bottom: 1px solid var(--cover-border); }
.evidence-list > div:first-child { padding-top: 0; }
.evidence-list > div:last-child { padding-bottom: 0; border-bottom: none; }
.evidence-list dt { color: var(--cover-ink); font-size: 13px; font-weight: 600; }
.evidence-list dd { color: var(--cover-muted); font-size: 13px; line-height: 1.8; }
.faq-grid { display: grid; grid-template-columns: 1fr 1.6fr; gap: 32px; background: var(--bg-card); border: 1px solid var(--cover-border); border-radius: 12px; padding: 24px; }
.faq-list details { border-bottom: 1px solid var(--cover-border); }
.faq-list details:last-child { border-bottom: none; }
.faq-list summary { list-style: none; cursor: pointer; padding: 14px 0; font-size: 13px; display: flex; justify-content: space-between; gap: 16px; }
.faq-list summary::-webkit-details-marker { display: none; }
.faq-list summary span { color: var(--cover-muted); }
.faq-list details[open] summary span { transform: rotate(45deg); }
.faq-list p { font-size: 13px; color: var(--cover-muted); line-height: 1.8; padding-bottom: 14px; }
.cover-cta { padding: 24px 0; }
.cta-inner { text-align: center; background: var(--bg-card); border: 1px solid var(--cover-border); border-radius: 12px; padding: 28px; }
.cta-inner .eyebrow, .cta-inner .hero-actions { justify-content: center; }
.cta-inner h2 { font-size: 23px; }
.cta-inner p { color: var(--cover-muted); font-size: 13px; }
.cover-footer { border-top: 1px solid var(--cover-border); background: var(--bg-card); }
.footer-inner { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 20px 0; color: var(--cover-muted); font-size: 12px; }
.footer-inner strong { color: var(--cover-ink); font-size: 16px; margin-right: 12px; }
.footer-inner a { color: var(--cover-muted); white-space: nowrap; }
@media (max-width: 1000px) {
  .hero-grid { gap: 24px; padding: 24px; }
  .hero-copy h1 { font-size: 28px; }
  .desktop-break { display: none; }
  .scope-grid > div { padding: 18px; }
  .feature-card { padding: 20px; }
  .workflow-grid { grid-template-columns: repeat(2, 1fr); }
  .behavior-copy, .behavior-demo { padding: 20px; }
  .demo-body { gap: 12px; }
  .demo-metrics > div { padding: 12px; }
}
@media (max-width: 760px) {
  .cover-container { width: calc(100% - 32px); }
  .cover-header { height: 60px; }
  .cover-header-inner { gap: 12px; }
  .cover-nav { display: none; }
  .cover-button-small { font-size: 12px; gap: 8px; padding: 8px 12px; }
  .cover-hero { padding-top: 16px; }
  .hero-grid { grid-template-columns: 1fr; gap: 22px; padding: 22px; }
  .hero-visual { width: 100%; max-width: 540px; }
  .hero-bottom > span:last-child { display: none; }
  .scope-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; padding-top: 16px; }
  .scope-grid strong { font-size: 26px; }
  .scope-grid .scope-text { font-size: 22px; }
  .cover-section { padding-top: 26px; scroll-margin-top: 76px; }
  .section-heading h2, .behavior-copy h2, .cover-cta h2 { font-size: 21px; }
  .feature-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .feature-card h3 { font-size: 15px; }
  .behavior-grid, .evidence-grid, .faq-grid { grid-template-columns: 1fr; gap: 22px; }
  .behavior-demo { width: 100%; }
  .demo-body { grid-template-columns: 1.5fr 1fr; gap: 22px; }
  .footer-inner { flex-wrap: wrap; gap: 12px; }
  .footer-inner > span:nth-child(2) { display: none; }
  .footer-inner > span:first-child span { display: block; margin-top: 4px; }
  .workflow-tools { flex-direction: column; gap: 12px; }
}
@media (max-width: 430px) {
  .cover-logo-icon { display:none }
  .brand-caption { max-width:108px; line-height:1.3 }
  .cover-header-actions { gap:6px }
  .hero-grid { padding: 18px; }
  .hero-copy h1 { font-size: 26px; }
  .cover-brand { font-size: 15px; }
  .cover-logo-icon { width: 32px; height: 32px; font-size: 17px; }
  .brand-caption { font-size: 9px; }
  .hero-product span { font-size: 10px; margin-left: 6px; }
  .feature-grid, .workflow-grid { grid-template-columns: 1fr; }
  .scope-grid > div { padding: 16px; }
  .scope-grid strong span { font-size: 12px; margin-left: 6px; }
  .visual-heading { padding: 14px 12px 10px; font-size: 12px; }
  .language-stack { padding: 0 12px 10px; }
  .visual-evidence > div { padding: 12px; gap: 7px; }
  .visual-evidence small { font-size: 10px; }
  .behavior-copy, .behavior-demo, .evidence-grid, .faq-grid { padding: 18px; }
  .demo-heading { flex-wrap: wrap; }
  .scenario-controls button { font-size: 11px; }
  .demo-body { grid-template-columns: 1fr; gap: 16px; }
  .demo-metrics { flex-direction: row; gap: 12px; }
  .demo-metrics > div { flex: 1; min-width: 0; padding: 12px; }
  .demo-metrics span, .demo-metrics small { font-size: 10px; }
  .demo-metrics strong { font-size: 24px; }
  .evidence-list > div { grid-template-columns: 90px 1fr; gap: 12px; }
  .hero-bottom { font-size: 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .cover-page *, .cover-page *::before, .cover-page *::after { transition: none !important; scroll-behavior: auto !important; }
}
</style>
