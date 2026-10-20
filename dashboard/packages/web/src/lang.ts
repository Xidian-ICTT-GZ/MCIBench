// 轻量语言层：只翻译界面文案，数据（模型名、题目名、语言名）保持原样。
// 由外层通过 ?lang=zh 激活；没有该参数时完全不介入，页面与原来一致。
const ZH: Record<string, string> = {
  'Dashboard': '仪表盘',
  'Problems': '题目',
  'Submissions': '提交记录',
  'Model Stats': '模型统计',
  'Generation Benchmark': '生成基准',
  'Translation Benchmark': '翻译基准',
  'Generation Pass@k by Model': '各模型生成 Pass@k',
  'Generation Language Pass@k': '各语言生成 Pass@k',
  'Translation Pair Pass@k': '各语言对翻译 Pass@k',
  'No generation Pass@k data': '暂无生成 Pass@k 数据',
  'No generation language data': '暂无语言维度数据',
  'No translation Pass@k data': '暂无翻译 Pass@k 数据',
  'No Pass@k data': '暂无 Pass@k 数据',
  'No generated code records': '暂无生成代码记录',
  'No translation result records': '暂无翻译结果记录',
  'Code Generation Benchmark': '代码生成基准',
  'Code Translation Benchmark': '代码翻译基准',
  'Description': '题目描述',
  'Generated Codes': '生成代码',
  'Interfaces': '接口',
  'Model': '模型',
  'Open Problem': '打开题目',
  'References': '参考解',
  'Search': '搜索',
  'Search by ID, title, or slug...': '按编号、标题或 slug 搜索…',
  'QID': '题号',
  'Status': '状态',
  'Source': '来源',
  'Target': '目标',
  'Source Lang': '源语言',
  'Target Lang': '目标语言',
  'Language': '语言',
  'Accepted': '通过',
  'Runtime Error': '运行错误',
  'Generation': '生成',
  'Translation': '翻译',
  'Translation Results': '翻译结果',
  'Benchmark Platform': '基准平台',
  'Task': '任务',
  'Title': '标题',
  'Wrong Answer': '答案错误',
  'Time Limit Exceeded': '超时',
  'Compile Error': '编译错误',
  'Memory Limit Exceeded': '内存超限',
  'Output Limit Exceeded': '输出超限',
}

let active = false

function translateText(node: Text) {
  const raw = node.nodeValue
  if (!raw) return
  const trimmed = raw.trim()
  if (!trimmed) return
  const hit = ZH[trimmed]
  if (!hit) return
  node.nodeValue = raw.replace(trimmed, hit)
}

function walk(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    translateText(root as Text)
    return
  }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  const el = root as HTMLElement
  if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'CANVAS') return
  for (const attr of ['title', 'placeholder', 'label']) {
    const value = el.getAttribute(attr)
    if (value && ZH[value.trim()]) el.setAttribute(attr, ZH[value.trim()])
  }
  let child = el.firstChild
  while (child) {
    const next = child.nextSibling
    walk(child)
    child = next
  }
}

export function initLang() {
  const lang = new URLSearchParams(location.search).get('lang')
  if (!lang || !lang.toLowerCase().startsWith('zh')) return
  active = true
  const start = () => {
    walk(document.body)
    new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach((node) => walk(node))
        if (record.type === 'characterData' && record.target) walk(record.target)
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start)
  else start()
}

export function langActive() { return active }
