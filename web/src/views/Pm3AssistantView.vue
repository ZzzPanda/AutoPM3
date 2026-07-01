<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { deletePm3Document, getPm3Document, getPm3DocumentDownloadUrl, listPm3Documents, type Pm3DocumentRecord, uploadPm3Document } from '../api'

type ViewKey = 'tasks' | 'results' | 'settings'
type SourceViewMode = 'markdown' | 'pdf'

interface ModelSettings {
  apiUrl: string
  modelName: string
  apiKey: string
}

interface CandidateVariant {
  variant: string
  protein: string
  gene: string
  patients: string
  context: string
  partner: string
  source: string
}

interface Pm3EvidenceRow {
  rowId?: string
  pmid: string
  title: string
  authors: string
  patientCount: string
  patientAge: string
  clinicalDisease: string
  clinicalPhenotype: string
  familyInfo: string
  pathogenicity: string
  zygosity: string
  transVariant: string
  cisVariant: string
  sourceIndex: string
  rawTableRow: string
  literatureBackground: string
  summary: string
  extractionProcess: string
  source: string
  fieldSources?: Record<string, string[]>
  fieldHighlights?: Record<string, string[]>
}

interface SourceChunk {
  id: string
  title: string
  reason: string
  quote: string
  startOffset?: number
  endOffset?: number
  evidenceTerms?: string[]
}

interface Pm3Section {
  title: string
  body: string
  sourceIds: string[]
  tone?: 'standard'
}

interface ParsedResultPayload {
  readonly candidates: CandidateVariant[]
  readonly pm3Rows: Pm3EvidenceRow[]
  readonly chunks: SourceChunk[]
  readonly documentMarkdown?: string
  readonly selectedVariant: string
}

const SETTINGS_KEY = 'autopm3:model-settings'
const LEFT_PANEL_COLLAPSED_KEY = 'autopm3:left-panel-collapsed'
const SOURCE_PANEL_WIDTH_KEY = 'autopm3:source-panel-width'
const SOURCE_PANEL_COLLAPSED_KEY = 'autopm3:source-panel-collapsed'
const SOURCE_PANEL_MIN_WIDTH = 360
const SOURCE_PANEL_MAX_WIDTH = 920

const currentView = ref<ViewKey>('tasks')
const sourceViewMode = ref<SourceViewMode>('markdown')
const uploadedFileName = ref('')
const selectedFiles = ref<File[]>([])
const fileInputKey = ref(0)
const parsing = ref(false)
const parsed = ref(false)
const storageMessage = ref('')
const listLoading = ref(false)
const deletingDocumentId = ref('')
const documentRecords = ref<Pm3DocumentRecord[]>([])
const activeChunkId = ref('chunk-1')
const activeRowId = ref('')
const activeDocumentId = ref('')
const activeDocumentMimeType = ref('')
const selectedPmid = ref('')
const selectedVariant = ref('')
const settingsSaved = ref(false)
const pdfPreviewUrl = ref('')
const pdfPreviewLoading = ref(false)
const pdfPreviewError = ref('')
const sourceDocumentRef = ref<HTMLElement | null>(null)
const leftPanelCollapsed = ref(false)
const sourcePanelWidth = ref(560)
const sourcePanelCollapsed = ref(false)
const resizingSourcePanel = ref(false)
let listPollTimer: number | undefined
let sourceResizeStartX = 0
let sourceResizeStartWidth = 0

const settings = ref<ModelSettings>({
  apiUrl: 'https://api.openai.com/v1',
  modelName: 'gpt-4o-mini',
  apiKey: '',
})

const ARTICLE_FIELDS: readonly { key: keyof Pm3EvidenceRow; label: string }[] = [
  { key: 'pmid', label: 'PMID' },
  { key: 'title', label: '标题' },
  { key: 'authors', label: '作者' },
  { key: 'literatureBackground', label: '文献背景' },
]

const PM3_COLUMNS: readonly { key: keyof Pm3EvidenceRow; label: string }[] = [
  { key: 'patientCount', label: '患者编号 / 病例' },
  { key: 'patientAge', label: '患者年龄' },
  { key: 'clinicalDisease', label: '患者临床疾病' },
  { key: 'clinicalPhenotype', label: '患者临床表型' },
  { key: 'familyInfo', label: '家系情况' },
  { key: 'pathogenicity', label: '致病性（作者结论是否致病/疑似致病/不致病可能有其它位点）' },
  { key: 'zygosity', label: '关联合子状态' },
  { key: 'transVariant', label: '反式(trans)位点' },
  { key: 'cisVariant', label: '顺式(cis)位点' },
  { key: 'sourceIndex', label: '来源索引（精准标注证据位置，格式为表编号+行号，用于回溯原始表格内容。）' },
  { key: 'rawTableRow', label: '表格原始行内容（保留表格原始文本，用于人工复核、过滤解析错误或假阳性。）' },
  { key: 'summary', label: '总结（示例：该变异已在[至少]XX名患有[疾病/表型]的个体中被检测到。在这些个体中，XX名为该变异与一个致病性或可能致病性变异xx的复合杂合，其中XX名通过[父母/家庭检测，其他方法]确认处于反式位置。XX名个体为该变异的纯合[PMID:xxxxx]' },
  { key: 'extractionProcess', label: 'AI提取过程' },
]

const candidates = ref<CandidateVariant[]>([])
const pm3Rows = ref<Pm3EvidenceRow[]>([])
const chunks = ref<SourceChunk[]>([])
const pm3Sections = ref<Pm3Section[]>([])
const documentMarkdown = ref('')
const activeFieldTerms = ref<string[]>([])

const parseStats = computed(() => [
  { label: '论文', value: uploadedFileName.value ? 1 : 0, className: 'done' },
  { label: '汇总行', value: pm3Rows.value.length, className: 'progress' },
  { label: '候选变异', value: candidates.value.length, className: 'todo' },
  { label: '来源', value: chunks.value.length, className: '' },
])

const activeChunk = computed(() => chunks.value.find((chunk) => chunk.id === activeChunkId.value) ?? chunks.value[0])
const activeDocumentIsPdf = computed(() => activeDocumentMimeType.value.includes('pdf') || uploadedFileName.value.toLowerCase().endsWith('.pdf'))
const matchedPm3Rows = computed(() => {
  const target = selectedVariant.value.trim()
  if (!target) return []
  return pm3Rows.value.filter((row) => rowMatchesVariant(row, target))
})
const displayedPm3Rows = computed(() => {
  const target = selectedVariant.value.trim()
  if (!target) return pm3Rows.value
  return matchedPm3Rows.value.length > 0 ? matchedPm3Rows.value : pm3Rows.value
})
const displayedRowNotice = computed(() => {
  if (!selectedVariant.value.trim()) return ''
  if (displayedPm3Rows.value.length === pm3Rows.value.length) return ''
  return `已按当前位点筛选：显示 ${displayedPm3Rows.value.length} / ${pm3Rows.value.length} 行`
})
const articleRow = computed(() => displayedPm3Rows.value[0] || pm3Rows.value[0])
const selectedFilesLabel = computed(() => {
  if (selectedFiles.value.length === 0) return ''
  if (selectedFiles.value.length === 1) return selectedFiles.value[0]?.name || ''
  return `已选择 ${selectedFiles.value.length} 个文件`
})
const resultsShellStyle = computed(() => ({
  gridTemplateColumns: [
    leftPanelCollapsed.value ? '44px' : 'minmax(220px, 300px)',
    'minmax(0, 1fr)',
    ...(sourcePanelCollapsed.value ? ['44px'] : ['8px', `minmax(280px, ${sourcePanelWidth.value}px)`]),
  ].join(' '),
}))
const md = new MarkdownIt({ html: true, breaks: true, linkify: true, typographer: true })

for (const rule of ['paragraph_open', 'heading_open', 'bullet_list_open', 'ordered_list_open', 'blockquote_open', 'fence', 'code_block', 'hr', 'table_open'] as const) {
  const original = md.renderer.rules[rule]
  md.renderer.rules[rule] = (tokens, idx, options, env, self) => {
    const token = tokens[idx]
    const lineOffsets = env?.lineOffsets as number[] | undefined
    if (token?.map && lineOffsets) {
      const startOffset = lineOffsets[Number(token.map[0])]
      const endOffset = lineOffsets[Number(token.map[1])]
      if (typeof startOffset === 'number' && typeof endOffset === 'number' && endOffset > startOffset) {
        token.attrSet('data-src-start', String(startOffset))
        token.attrSet('data-src-end', String(endOffset))
      }
    }
    return original ? original(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options)
  }
}

const originalHtmlBlockRule = md.renderer.rules.html_block
md.renderer.rules.html_block = (tokens, idx, options, env, self) => {
  const content = String(tokens[idx]?.content ?? '').trim()
  const pageMatch = content.match(/^<!--\s*page:\s*(\d+)\s*-->$/)
  if (pageMatch) return `<div class="page-marker" data-page="${pageMatch[1]}">— 第 ${pageMatch[1]} 页 —</div>`
  return originalHtmlBlockRule ? originalHtmlBlockRule(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options)
}

function loadSettings(): void {
  const raw = window.localStorage.getItem(SETTINGS_KEY)
  if (!raw) return
  try {
    settings.value = { ...settings.value, ...JSON.parse(raw) }
  } catch {
    window.localStorage.removeItem(SETTINGS_KEY)
  }
}

function saveSettings(): void {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings.value))
  settingsSaved.value = true
  window.setTimeout(() => {
    settingsSaved.value = false
  }, 1600)
}

function loadSourcePanelState(): void {
  const savedWidth = Number(window.localStorage.getItem(SOURCE_PANEL_WIDTH_KEY))
  if (Number.isFinite(savedWidth) && savedWidth > 0) {
    sourcePanelWidth.value = clampSourcePanelWidth(savedWidth)
  }
  sourcePanelCollapsed.value = window.localStorage.getItem(SOURCE_PANEL_COLLAPSED_KEY) === 'true'
  leftPanelCollapsed.value = window.localStorage.getItem(LEFT_PANEL_COLLAPSED_KEY) === 'true'
}

function clampSourcePanelWidth(width: number): number {
  return Math.min(SOURCE_PANEL_MAX_WIDTH, Math.max(SOURCE_PANEL_MIN_WIDTH, Math.round(width)))
}

function persistSourcePanelState(): void {
  window.localStorage.setItem(SOURCE_PANEL_WIDTH_KEY, String(sourcePanelWidth.value))
  window.localStorage.setItem(SOURCE_PANEL_COLLAPSED_KEY, String(sourcePanelCollapsed.value))
}

function setLeftPanelCollapsed(collapsed: boolean): void {
  leftPanelCollapsed.value = collapsed
  window.localStorage.setItem(LEFT_PANEL_COLLAPSED_KEY, String(collapsed))
}

function setSourcePanelCollapsed(collapsed: boolean): void {
  sourcePanelCollapsed.value = collapsed
  persistSourcePanelState()
  if (!collapsed && sourceViewMode.value === 'pdf') void loadPdfPreview()
  if (!collapsed && sourceViewMode.value === 'markdown') void nextTick(() => annotateBlocksByChunks())
}

function startSourcePanelResize(event: MouseEvent): void {
  if (sourcePanelCollapsed.value) return
  resizingSourcePanel.value = true
  sourceResizeStartX = event.clientX
  sourceResizeStartWidth = sourcePanelWidth.value
  document.body.classList.add('source-panel-resizing')
  window.addEventListener('mousemove', resizeSourcePanel)
  window.addEventListener('mouseup', stopSourcePanelResize)
}

function resizeSourcePanel(event: MouseEvent): void {
  if (!resizingSourcePanel.value) return
  const delta = sourceResizeStartX - event.clientX
  sourcePanelWidth.value = clampSourcePanelWidth(sourceResizeStartWidth + delta)
}

function stopSourcePanelResize(): void {
  if (!resizingSourcePanel.value) return
  resizingSourcePanel.value = false
  document.body.classList.remove('source-panel-resizing')
  window.removeEventListener('mousemove', resizeSourcePanel)
  window.removeEventListener('mouseup', stopSourcePanelResize)
  persistSourcePanelState()
}

function handleFile(event: Event): void {
  const input = event.target as HTMLInputElement
  selectedFiles.value = Array.from(input.files ?? [])
  uploadedFileName.value = selectedFilesLabel.value
}

function sourceIdFromHash(hash: string): string {
  return hash.startsWith('#source-') ? hash.slice('#source-'.length) : ''
}

function routeState(): { view: ViewKey; documentId: string; pmid: string; rowId: string; sourceId: string } {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  const normalizedView: ViewKey = view === 'results' || view === 'settings' ? view : 'tasks'
  return {
    view: normalizedView,
    documentId: params.get('documentId') || '',
    pmid: params.get('pmid') || '',
    rowId: params.get('rowId') || '',
    sourceId: sourceIdFromHash(window.location.hash),
  }
}

function setRouteState(
  view: ViewKey,
  options: { documentId?: string; pmid?: string; rowId?: string; sourceId?: string; replace?: boolean } = {},
): void {
  const url = new URL(window.location.href)
  url.searchParams.set('view', view)
  if (view === 'results' && options.documentId) {
    url.searchParams.set('documentId', options.documentId)
    if (options.pmid) url.searchParams.set('pmid', options.pmid)
    else url.searchParams.delete('pmid')
    if (options.rowId) url.searchParams.set('rowId', options.rowId)
    else url.searchParams.delete('rowId')
    url.hash = options.sourceId ? sourceAnchorId(options.sourceId) : ''
  } else {
    url.searchParams.delete('documentId')
    url.searchParams.delete('pmid')
    url.searchParams.delete('rowId')
    url.hash = ''
  }
  const nextUrl = `${url.pathname}${url.search}${url.hash}`
  const method = options.replace ? 'replaceState' : 'pushState'
  window.history[method](null, '', nextUrl)
}

function navigateTo(view: ViewKey): void {
  currentView.value = view
  if (view === 'tasks') void loadDocumentList()
  else updateListPolling()
  setRouteState(view, {
    documentId: activeDocumentId.value,
    pmid: selectedPmid.value,
    rowId: selectedRowId.value,
  })
}

function firstPmid(payload: Partial<ParsedResultPayload>): string {
  return payload.pm3Rows?.find((row) => row.pmid.trim())?.pmid || ''
}

function stableRowId(row: Pm3EvidenceRow, index: number): string {
  const basis = [
    row.pmid,
    row.patientCount,
    row.transVariant,
    row.sourceIndex,
    row.rawTableRow,
  ].join('|')
  let hash = 0
  for (let i = 0; i < basis.length; i += 1) {
    hash = (hash * 31 + basis.charCodeAt(i)) >>> 0
  }
  return row.rowId || `${row.pmid || 'pmid'}-${index + 1}-${hash.toString(36)}`
}

function rowKey(row: Pm3EvidenceRow): string {
  return row.rowId || `${row.pmid}-${row.source}-${row.patientCount}-${row.transVariant}`
}

const selectedRowId = computed(() => activeRowId.value)

function applyParsedPayload(
  payload: Partial<ParsedResultPayload>,
  fileName: string,
  options: { documentId?: string; mimeType?: string; pmid?: string; rowId?: string; sourceId?: string } = {},
): boolean {
  if (!payload.candidates || !payload.pm3Rows || !payload.chunks) {
    storageMessage.value = '该记录缺少可展示的解析结果。'
    return false
  }
  const normalizedRows = payload.pm3Rows.map((row, index) => ({ ...row, rowId: stableRowId(row, index) }))
  const selectedRow =
    (options.rowId && normalizedRows.find((row) => row.rowId === options.rowId)) ||
    (options.pmid && normalizedRows.find((row) => row.pmid === options.pmid)) ||
    normalizedRows[0]
  const pmid = selectedRow?.pmid || firstPmid(payload)
  candidates.value = payload.candidates
  pm3Rows.value = normalizedRows
  chunks.value = payload.chunks
  documentMarkdown.value = payload.documentMarkdown || payload.chunks.map((chunk) => chunk.quote).join('\n\n')
  activeDocumentId.value = options.documentId || ''
  activeDocumentMimeType.value = options.mimeType || ''
  pdfPreviewUrl.value = ''
  pdfPreviewError.value = ''
  selectedPmid.value = pmid
  activeRowId.value = selectedRow?.rowId || ''
  selectedVariant.value = payload.selectedVariant || payload.candidates[0]?.variant || ''
  uploadedFileName.value = fileName
  pm3Sections.value = []
  activeChunkId.value = options.sourceId || (selectedRow ? primarySourceForRow(selectedRow) : payload.chunks[0]?.id || 'chunk-1')
  parsed.value = true
  return true
}

function applyDemoParsedResult(): void {
  uploadedFileName.value ||= 'GALT_c.821-7AG_PM3汇总样例.md'
  applyParsedPayload({
    candidates: [
    {
      variant: 'NM_000155.4:c.821-7A>G',
      protein: 'Exon 9 deletion',
      gene: 'GALT',
      patients: '1名（本研究），累计3名（含既往研究）',
      context: '复合杂合子',
      partner: 'c.286_299delGACAACGACTTCCC（p.Asp96Serfs*5）',
      source: 'chunk-1',
    },
    {
      variant: 'NM_000155.3:c.821-7A>G',
      protein: 'p.?',
      gene: 'GALT',
      patients: '1名',
      context: '杂合子（Het）',
      partner: '未明确提及',
      source: 'chunk-2',
    },
    ],
    pm3Rows: [
    {
      pmid: '25124065',
      title: 'Novel GALT variations and mutation spectrum in the Korean population with decreased galactose-1-phosphate uridyltransferase activity',
      authors: 'Rihwa Choi, Kyoung Il Jo, Dae-Hyun Ko, Dong Hwan Lee, Junghan Song, Dong-Kyu Jin, Chang-Seok Ki, Soo-Youn Lee, Jong-Won Kim, Yong-Wha Lee, Hyung-Doo Park',
      patientCount: '1名（本研究），累计3名（含既往研究）',
      patientAge: '1.8个月（本研究患者，女性）',
      clinicalDisease: '经典半乳糖血症（Classic galactosemia，OMIM #230400），GALT酶活性降低',
      clinicalPhenotype: '新生儿筛查半乳糖血症阳性，GALT酶活性7.3 μmol/h/g Hb（正常参考值20–35 μmol/h/g Hb），无明显特殊临床症状',
      familyInfo: '本研究13名患者均为无关患者，无近亲婚配家庭相关描述',
      pathogenicity: '致病。该变异为内含子突变，可导致剪接异常（第9外显子缺失），属于已知的致病性突变',
      zygosity: '复合杂合子',
      transVariant: 'c.286_299delGACAACGACTTCCC（p.Asp96Serfs*5），新的可能致病性变异',
      cisVariant: '无',
      sourceIndex: '表1（13例GALT酶活性降低患者的GALT基因型个体特征表）病例2行；表3（GALT基因突变汇总表）IVS 8 c.821-7A > G行',
      rawTableRow: '表1病例2行：Case no.2，Age (month)1.8，Sex F，Location IVS 8，Nucleotide change* c.821-7A > G，Amino acid change Exon 9 deletion，GALT activity† 7.3 μmol/h/g Hb，Category‡ G/G；表3行：Splicing aberration，IVS 8 c.821-7A > G，Exon 9 deletion，3 Ko et al. [14], this study',
      literatureBackground: '本研究为韩国人群GALT基因突变谱的研究，纳入13名新生儿筛查半乳糖血症阳性、GALT酶活性降低的无关患者，对GALT基因进行直接测序和硅基分析，评估新变异对GALT酶活性的影响，最终提供了韩国人群GALT基因突变的全面更新谱。',
      summary: '该变异已在至少3名患有经典半乳糖血症（GALT酶活性降低）的个体中被检测到。在这些个体中，1名为该变异与一个可能致病性变异c.286_299delGACAACGACTTCCC (p.Asp96Serfs*5)的复合杂合，该变异可导致第9外显子缺失的剪接异常，属于已知的致病性突变[PMID:25124065]',
      extractionProcess: '定位表1病例2行确认目标位点、患者年龄、酶活性和合子状态；定位表3 IVS 8 c.821-7A > G行确认既往报道累计人数和剪接异常；综合正文研究背景生成总结。',
      source: 'chunk-1',
    },
    ],
    chunks: [
    {
      id: 'chunk-1',
      title: 'Chunk 1',
      reason: '表1病例2行与表3 IVS 8行',
      quote: 'Case no.2, Age (month) 1.8, Sex F, Location IVS 8, Nucleotide change c.821-7A > G, Amino acid change Exon 9 deletion, GALT activity 7.3 μmol/h/g Hb, Category G/G.',
    },
    {
      id: 'chunk-2',
      title: 'Chunk 2',
      reason: 'supplementary tables 中的 GALT c.821-7A>G 记录',
      quote: 'GALT(NM_000155.3), c.821-7A>G, p.?, Pathogenic, Het; confirmed by Sanger sequencing.',
    },
    ],
    selectedVariant: 'NM_000155.4:c.821-7A>G',
  }, uploadedFileName.value)
}

function hasCompleteModelSettings(): boolean {
  return Boolean(settings.value.apiUrl.trim() && settings.value.modelName.trim() && settings.value.apiKey.trim())
}

function isTerminalStatus(status: string): boolean {
  return status === 'parsed' || status === 'failed'
}

function isParsedRecord(record: Pm3DocumentRecord): boolean {
  return record.status === 'parsed'
}

function parsedPayload(record: Pm3DocumentRecord): Partial<ParsedResultPayload> {
  return (record.parsedResult || {}) as Partial<ParsedResultPayload>
}

function pm3RowCount(record: Pm3DocumentRecord): number {
  return parsedPayload(record).pm3Rows?.length || 0
}

function candidateCount(record: Pm3DocumentRecord): number {
  return parsedPayload(record).candidates?.length || 0
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    processing: '解析中',
    parsed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

async function parseMarkdown(): Promise<void> {
  parsing.value = true
  storageMessage.value = ''
  if (selectedFiles.value.length > 0 && !hasCompleteModelSettings()) {
    storageMessage.value = '请先在模型设置页填写 API URL、Model Name 和 API Key，然后再提交解析任务。'
    navigateTo('settings')
    parsing.value = false
    return
  }

  if (selectedFiles.value.length > 0) {
    try {
      const results = await Promise.allSettled(
        selectedFiles.value.map((file) =>
          uploadPm3Document({
            file,
            modelSettings: settings.value,
          }),
        ),
      )
      const succeeded = results.filter((result) => result.status === 'fulfilled')
      const failed = results.filter((result) => result.status === 'rejected')
      const successNames = succeeded
        .map((result) => (result as PromiseFulfilledResult<Pm3DocumentRecord>).value.fileName)
        .slice(0, 3)
        .join('、')
      storageMessage.value =
        failed.length > 0
          ? `已提交 ${succeeded.length} 个任务，${failed.length} 个失败。${successNames ? `成功提交：${successNames}` : ''}`
          : `已提交 ${succeeded.length} 个解析任务。后台会继续解析，完成后可在列表中查看结果。`
      if (succeeded.length > 0) {
        selectedFiles.value = []
        uploadedFileName.value = ''
        fileInputKey.value += 1
      }
      await loadDocumentList()
      currentView.value = 'tasks'
      setRouteState('tasks')
    } catch (err) {
      storageMessage.value = err instanceof Error ? `解析或存储未完成：${err.message}` : '解析或存储未完成：后端不可用'
    }
  } else {
    await new Promise((resolve) => window.setTimeout(resolve, 520))
    applyDemoParsedResult()
    storageMessage.value = '未选择实际文件，当前为本地演示解析结果；上传 PDF / Markdown 后会调用真实大模型。'
    currentView.value = 'results'
    setRouteState('results')
  }
  parsing.value = false
}

async function loadDocumentList(): Promise<void> {
  listLoading.value = true
  try {
    documentRecords.value = await listPm3Documents()
    updateListPolling()
  } catch (err) {
    storageMessage.value = err instanceof Error ? `列表加载失败：${err.message}` : '列表加载失败：后端不可用'
  } finally {
    listLoading.value = false
  }
}

function openRecord(record: Pm3DocumentRecord, pmid = firstPmid(parsedPayload(record))): void {
  if (!isParsedRecord(record)) {
    storageMessage.value = record.status === 'failed' ? `解析失败：${record.errorMessage || '未知错误'}` : `任务仍在${statusLabel(record.status)}，完成后才能查看结果。`
    return
  }
  const payload = parsedPayload(record)
  if (applyParsedPayload(payload, record.fileName, { documentId: record.id, mimeType: record.mimeType, pmid })) {
    currentView.value = 'results'
    setRouteState('results', { documentId: record.id, pmid: selectedPmid.value, rowId: selectedRowId.value, sourceId: activeChunkId.value })
    updateListPolling()
  }
}

function updateListPolling(): void {
  const shouldPoll = currentView.value === 'tasks' && documentRecords.value.some((record) => !isTerminalStatus(record.status))
  if (shouldPoll && !listPollTimer) {
    listPollTimer = window.setInterval(() => {
      void loadDocumentList()
    }, 2500)
  }
  if (!shouldPoll && listPollTimer) {
    window.clearInterval(listPollTimer)
    listPollTimer = undefined
  }
}

async function deleteRecord(record: Pm3DocumentRecord): Promise<void> {
  const confirmed = window.confirm(`确认删除「${record.fileName}」吗？这会同时删除 S3 文件和 PostgreSQL 中的解析结果。`)
  if (!confirmed) return
  deletingDocumentId.value = record.id
  try {
    await deletePm3Document(record.id)
    documentRecords.value = documentRecords.value.filter((item) => item.id !== record.id)
    storageMessage.value = `已删除：${record.fileName}`
    if (activeDocumentId.value === record.id) {
      activeDocumentId.value = ''
      activeDocumentMimeType.value = ''
      uploadedFileName.value = ''
      selectedFiles.value = []
      fileInputKey.value += 1
      candidates.value = []
      pm3Rows.value = []
      activeRowId.value = ''
      chunks.value = []
      documentMarkdown.value = ''
      pm3Sections.value = []
      parsed.value = false
      selectedPmid.value = ''
      selectedVariant.value = ''
      pdfPreviewUrl.value = ''
      pdfPreviewError.value = ''
      currentView.value = 'tasks'
      setRouteState('tasks', { replace: true })
    }
  } catch (err) {
    storageMessage.value = err instanceof Error ? `删除失败：${err.message}` : '删除失败：后端不可用'
  } finally {
    deletingDocumentId.value = ''
  }
}

async function openRecordFromRoute(): Promise<void> {
  const state = routeState()
  currentView.value = state.view
  if (state.view === 'tasks') {
    await loadDocumentList()
    setRouteState('tasks', { replace: true })
    return
  }
  if (state.view !== 'results' || !state.documentId) return
  try {
    const record = await getPm3Document(state.documentId)
    const payload = record.parsedResult as Partial<ParsedResultPayload>
    if (applyParsedPayload(payload, record.fileName, { documentId: record.id, mimeType: record.mimeType, pmid: state.pmid, rowId: state.rowId, sourceId: state.sourceId })) {
      currentView.value = 'results'
      setRouteState('results', { documentId: record.id, pmid: selectedPmid.value, rowId: selectedRowId.value, sourceId: activeChunkId.value, replace: true })
    }
  } catch (err) {
    storageMessage.value = err instanceof Error ? `结果加载失败：${err.message}` : '结果加载失败：后端不可用'
    currentView.value = 'tasks'
    await loadDocumentList()
  }
}

function focusEvidenceRow(row: Pm3EvidenceRow): void {
  selectedPmid.value = row.pmid
  activeRowId.value = row.rowId || ''
  const sourceId = primarySourceForRow(row)
  focusSource(sourceId)
  if (activeDocumentId.value) {
    setRouteState('results', { documentId: activeDocumentId.value, pmid: row.pmid, rowId: row.rowId, sourceId, replace: true })
  }
}

async function loadPdfPreview(): Promise<void> {
  if (sourceViewMode.value !== 'pdf') return
  pdfPreviewError.value = ''
  if (!activeDocumentId.value) {
    pdfPreviewUrl.value = ''
    pdfPreviewError.value = '当前结果没有关联落库文件，无法预览 PDF。'
    return
  }
  if (!activeDocumentIsPdf.value) {
    pdfPreviewUrl.value = ''
    pdfPreviewError.value = '当前上传文件不是 PDF，请切回 Markdown 查看原文片段。'
    return
  }
  if (pdfPreviewUrl.value) return
  pdfPreviewLoading.value = true
  try {
    pdfPreviewUrl.value = await getPm3DocumentDownloadUrl(activeDocumentId.value)
  } catch (err) {
    pdfPreviewError.value = err instanceof Error ? `PDF 加载失败：${err.message}` : 'PDF 加载失败：后端不可用'
  } finally {
    pdfPreviewLoading.value = false
  }
}

function setSourceViewMode(mode: SourceViewMode): void {
  sourceViewMode.value = mode
  if (mode === 'pdf') void loadPdfPreview()
}

function runPm3(): void {
  if (!selectedVariant.value.trim()) return
  const sourceRows = matchedPm3Rows.value
  const mergedSummary = sourceRows.map((row) => row.summary).join('；')
  pm3Sections.value = [
    {
      title: '标准化结论',
      tone: 'standard',
      body: mergedSummary || `该变异 ${selectedVariant.value} 暂无足够结构化证据生成 PM3 结论。`,
      sourceIds: sourceRows.map((row) => row.source),
    },
    {
      title: '患者与疾病证据',
      body: sourceRows.map((row) => `${row.patientCount}；${row.clinicalDisease}；${row.clinicalPhenotype}`).join(' / '),
      sourceIds: sourceRows.map((row) => row.source),
    },
    {
      title: '合子状态 / trans / cis',
      body: sourceRows.map((row) => `合子状态：${row.zygosity}；trans位点：${row.transVariant}；cis位点：${row.cisVariant}；家系情况：${row.familyInfo}`).join(' / '),
      sourceIds: sourceRows.map((row) => row.source),
    },
    {
      title: '来源索引与人工复核',
      body: sourceRows.map((row) => `${row.sourceIndex}。原始行：${row.rawTableRow}`).join(' / '),
      sourceIds: sourceRows.map((row) => row.source),
    },
  ]
}

function toggleCandidateVariant(item: CandidateVariant): void {
  if (selectedVariant.value === item.variant) {
    selectedVariant.value = ''
    pm3Sections.value = []
    activeFieldTerms.value = []
    focusSource(item.source)
    return
  }
  selectedVariant.value = item.variant
  pm3Sections.value = []
  focusSource(item.source)
}

function normalizeVariantText(value: string): string {
  return value
    .toLowerCase()
    .replaceAll('&gt;', '>')
    .replaceAll('&lt;', '<')
    .replaceAll('＞', '>')
    .replaceAll('＜', '<')
    .replace(/[\s_]/g, '')
}

function variantNeedles(value: string): string[] {
  const decoded = value
    .toLowerCase()
    .replaceAll('&gt;', '>')
    .replaceAll('&lt;', '<')
    .replaceAll('＞', '>')
    .replaceAll('＜', '<')
  const needles = new Set<string>()
  const hgvsMatches = decoded.match(/[cp]\.[a-z0-9*?]+(?:[>_<+\-][a-z0-9*?]+)*/g) || []
  for (const match of hgvsMatches) {
    needles.add(normalizeVariantText(match).replace(/[()[\]]/g, ''))
  }
  const normalized = normalizeVariantText(decoded)
  if (normalized) needles.add(normalized.replace(/[()[\]]/g, ''))
  return [...needles].filter((needle) => needle.length >= 5)
}

function rowMatchesVariant(row: Pm3EvidenceRow, variant: string): boolean {
  const needles = variantNeedles(variant)
  if (!needles.length) return true
  const haystack = normalizeVariantText([
    row.transVariant,
    row.cisVariant,
    row.rawTableRow,
    row.summary,
    row.extractionProcess,
    row.sourceIndex,
  ].join(' '))
  return needles.some((needle) => haystack.includes(needle))
}

function focusSource(chunkId: string): void {
  revealSourceChunk(chunkId, [])
}

function focusCitation(chunkId: string, event?: Event): void {
  event?.preventDefault()
  event?.stopPropagation()
  event?.stopImmediatePropagation()
  revealSourceChunk(chunkId, [])
}

function handleSummaryTableClick(event: Event): void {
  const target = event.target
  if (!(target instanceof Element)) return
  const citation = target.closest<HTMLElement>('.field-citation')
  const chunkId = citation?.dataset.sourceId
  if (!chunkId) return
  focusCitation(chunkId, event)
}

function handleSourceHashChange(): void {
  const sourceId = sourceIdFromHash(window.location.hash)
  if (!sourceId || sourceId === activeChunkId.value) return
  revealSourceChunk(sourceId, [])
}

function revealSourceChunk(chunkId: string, terms: string[]): void {
  if (!chunkId) return
  activeChunkId.value = chunkId
  activeFieldTerms.value = terms
  sourceViewMode.value = 'markdown'
  if (sourcePanelCollapsed.value) setSourcePanelCollapsed(false)
  void scrollSource()
}

async function scrollSource(): Promise<void> {
  await nextTick()
  await new Promise((resolve) => window.requestAnimationFrame(resolve))
  annotateBlocksByChunks()
  const targets = sourceTargets(activeChunkId.value)
  const loweredTerms = activeFieldTerms.value.map((term) => term.toLowerCase())
  const target =
    targets.find((el) => loweredTerms.some((term) => el.textContent?.toLowerCase().includes(term))) ||
    targets[0]
  clearTermHighlights()
  if (target) {
    target.classList.add('chunk-highlight', 'is-active')
    highlightTerms(target, activeFieldTerms.value)
    scrollElementIntoSourceView(target)
    window.requestAnimationFrame(() => scrollActiveSourceIntoView())
    window.setTimeout(() => scrollActiveSourceIntoView(), 120)
    window.setTimeout(() => scrollActiveSourceIntoView(), 360)
    window.setTimeout(() => scrollActiveSourceIntoView(), 720)
  }
}

function scrollActiveSourceIntoView(): void {
  const targets = sourceTargets(activeChunkId.value)
  const loweredTerms = activeFieldTerms.value.map((term) => term.toLowerCase())
  const target =
    targets.find((el) => loweredTerms.some((term) => el.textContent?.toLowerCase().includes(term))) ||
    targets[0]
  if (target) scrollElementIntoSourceView(target)
}

function scrollElementIntoSourceView(target: HTMLElement): void {
  const root = document.querySelector<HTMLElement>('.source-document') || sourceDocumentRef.value
  if (!root) return
  const targetTop = elementTopWithin(target, root)
  const targetMiddle = targetTop + target.offsetHeight / 2
  const top = Math.max(0, targetMiddle - root.clientHeight / 2)
  root.style.scrollBehavior = 'auto'
  root.scrollTo({ top, behavior: 'auto' })
  root.scrollTo(0, top)
  root.scroll({ top, left: 0, behavior: 'auto' })
  root.scrollBy(0, top - root.scrollTop)
  try {
    root.scrollTop = top
  } catch {
    // Some embedded browser wrappers expose scrollTop as read-only; scrollTo/scroll still handle real browsers.
  }
  const anchorId = sourceAnchorId(activeChunkId.value)
  target.id = anchorId
  if (window.location.hash === `#${anchorId}`) {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }
  window.location.hash = anchorId
}

function sourceAnchorId(chunkId: string): string {
  return `source-${chunkId.replace(/[^A-Za-z0-9_-]+/g, '-')}`
}

function elementTopWithin(target: HTMLElement, root: HTMLElement): number {
  let top = 0
  let current: HTMLElement | null = target
  while (current && current !== root) {
    top += current.offsetTop
    current = current.offsetParent as HTMLElement | null
  }
  if (current === root) return top
  return target.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
}

function sourceTargets(chunkId: string): HTMLElement[] {
  const root = sourceDocumentRef.value
  if (!root || !chunkId) return []
  if (chunkId.startsWith('table-')) {
    const table = root.querySelector<HTMLElement>(`table[data-table-source="${cssEscape(chunkId)}"]`)
    if (table) return [table]
  }
  const directTargets = Array.from(root.querySelectorAll<HTMLElement>(`[data-chunk-id~="${cssEscape(chunkId)}"]`))
  if (directTargets.length > 0) {
    if (!chunkId.startsWith('table-')) return directTargets
    const directTables = directTargets.filter((target) => target.tagName.toLowerCase() === 'table')
    if (directTables.length > 0) return directTables
  }
  if (!chunkId.startsWith('table-')) return []
  const chunk = chunks.value.find((item) => item.id === chunkId)
  if (!chunk) return []
  const chunkText = compactForTableMatch(chunk.quote)
  return Array.from(root.querySelectorAll<HTMLElement>('table')).filter((candidate) => {
    const tableText = compactForTableMatch(candidate.textContent || '')
    return Boolean(tableText && (chunkText.includes(tableText.slice(0, 80)) || tableText.includes(chunkText.slice(0, 80))))
  })
}

function renderDocument(): string {
  if (!documentMarkdown.value.trim()) return '<div class="source-empty">暂无可回溯原文。请重新解析论文。</div>'
  const html = md.render(documentMarkdown.value, { lineOffsets: lineOffsets(documentMarkdown.value) })
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['data-page', 'data-src-start', 'data-src-end', 'data-chunk-id'],
  })
}

function renderActiveChunk(): string {
  if (!activeChunk.value?.quote) return '<div class="source-empty compact">暂无当前引用。</div>'
  return DOMPurify.sanitize(md.render(activeChunk.value.quote))
}

function lineOffsets(text: string): number[] {
  const offsets = [0]
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '\n') offsets.push(i + 1)
  }
  offsets.push(text.length)
  return offsets
}

function annotateBlocksByChunks(): void {
  const root = sourceDocumentRef.value
  if (!root) return
  root.querySelectorAll<HTMLElement>('[data-chunk-id]').forEach((el) => {
    el.removeAttribute('data-chunk-id')
    el.classList.remove('chunk-highlight', 'is-active')
  })
  const blocks = Array.from(root.querySelectorAll<HTMLElement>('[data-src-start][data-src-end]'))
  for (const block of blocks) {
    const start = Number(block.dataset.srcStart)
    const end = Number(block.dataset.srcEnd)
    const ids = chunks.value
      .filter((chunk) => typeof chunk.startOffset === 'number' && typeof chunk.endOffset === 'number')
      .filter((chunk) => start < (chunk.endOffset ?? 0) && end > (chunk.startOffset ?? 0))
      .map((chunk) => chunk.id)
    if (ids.length > 0) {
      block.setAttribute('data-chunk-id', ids.join(' '))
      const tableId = ids.find((id) => id.startsWith('table-'))
      if (block.tagName.toLowerCase() === 'table' && tableId) {
        block.setAttribute('data-table-source', tableId)
        block.id = sourceAnchorId(tableId)
      }
    }
  }
  annotateRenderedTables(root)
}

function annotateRenderedTables(root: HTMLElement): void {
  const tableChunks = chunks.value.filter((chunk) => chunk.id.startsWith('table-')).sort(compareChunksByPosition)
  if (!tableChunks.length) return
  const tables = Array.from(root.querySelectorAll<HTMLElement>('table'))
  if (!tables.length) return

  const usedIds = new Set<string>()
  for (const table of tables) {
    const directMatch = tableChunks.find((chunk) => !usedIds.has(chunk.id) && tableOverlapsChunk(table, chunk))
    if (directMatch) {
      applyTableChunk(table, directMatch)
      usedIds.add(directMatch.id)
    }
  }

  for (let index = 0; index < tables.length; index += 1) {
    const table = tables[index]
    if (table.dataset.tableSource) continue
    const matched = bestTableChunkMatch(table, tableChunks, usedIds, index, tables.length)
    if (!matched) continue
    applyTableChunk(table, matched)
    usedIds.add(matched.id)
  }
}

function applyTableChunk(table: HTMLElement, chunk: SourceChunk): void {
  const existing = table.getAttribute('data-chunk-id')
  const ids = new Set((existing || '').split(/\s+/).filter(Boolean))
  ids.add(chunk.id)
  table.setAttribute('data-chunk-id', [...ids].join(' '))
  table.setAttribute('data-table-source', chunk.id)
  table.id = sourceAnchorId(chunk.id)
}

function tableOverlapsChunk(table: HTMLElement, chunk: SourceChunk): boolean {
  const start = Number(table.dataset.srcStart)
  const end = Number(table.dataset.srcEnd)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return false
  if (typeof chunk.startOffset !== 'number' || typeof chunk.endOffset !== 'number') return false
  return start < chunk.endOffset && end > chunk.startOffset
}

function bestTableChunkMatch(
  table: HTMLElement,
  tableChunks: SourceChunk[],
  usedIds: Set<string>,
  tableIndex: number,
  tableCount: number,
): SourceChunk | undefined {
  const tableText = compactForTableMatch(table.textContent || '')
  if (!tableText) return undefined
  const available = tableChunks.filter((chunk) => !usedIds.has(chunk.id))
  if (available.length === 0) return undefined
  const chunkAtSameIndex = tableChunks[tableIndex]
  let best: { chunk: SourceChunk; score: number } | undefined
  for (const chunk of available) {
    const chunkText = compactForTableMatch(chunk.quote)
    if (!chunkText) continue
    let score = sourceMatchScore(tableText, chunkText)
    if (tableCount === tableChunks.length && chunk.id === chunkAtSameIndex?.id) score += 5000
    if (!best || score > best.score) best = { chunk, score }
  }
  return best && best.score > 0 ? best.chunk : undefined
}

function compareChunksByPosition(left: SourceChunk, right: SourceChunk): number {
  const leftOffset = typeof left.startOffset === 'number' ? left.startOffset : Number.POSITIVE_INFINITY
  const rightOffset = typeof right.startOffset === 'number' ? right.startOffset : Number.POSITIVE_INFINITY
  if (leftOffset !== rightOffset) return leftOffset - rightOffset
  return naturalIdNumber(left.id) - naturalIdNumber(right.id)
}

function naturalIdNumber(value: string): number {
  return Number(value.match(/\d+$/)?.[0] || Number.MAX_SAFE_INTEGER)
}

function sourceMatchScore(left: string, right: string): number {
  const minLength = Math.min(left.length, right.length)
  if (minLength === 0) return 0
  let score = 0
  if (right.includes(left)) score += Math.min(left.length, 5000)
  if (left.includes(right)) score += Math.min(right.length, 5000)
  const sampleSizes = [240, 160, 80]
  for (const size of sampleSizes) {
    const leftHead = left.slice(0, size)
    const rightHead = right.slice(0, size)
    if (leftHead.length >= 20 && right.includes(leftHead)) score += size
    if (rightHead.length >= 20 && left.includes(rightHead)) score += size
  }
  return score
}

function compactForSourceMatch(value: string): string {
  return value.replace(/[^\p{L}\p{N}]+/gu, '').toLowerCase()
}

function compactForTableMatch(value: string): string {
  return compactForSourceMatch(value.replace(/<[^>]*>/g, ' '))
}

function primarySourceForRow(row: Pm3EvidenceRow): string {
  if (row.source.startsWith('table-')) return row.source
  const tableFields: Array<keyof Pm3EvidenceRow> = ['rawTableRow', 'patientCount', 'patientAge', 'transVariant', 'clinicalDisease', 'clinicalPhenotype']
  for (const field of tableFields) {
    const tableSource = row.fieldSources?.[String(field)]?.find((source) => source.startsWith('table-'))
    if (tableSource) return tableSource
  }
  return row.source
}

function fieldChunkIds(row: Pm3EvidenceRow, field: keyof Pm3EvidenceRow): string[] {
  const fromField = row.fieldSources?.[String(field)] ?? []
  return fromField.length > 0 ? fromField : [row.source].filter(Boolean)
}

function fieldTerms(row: Pm3EvidenceRow, field: keyof Pm3EvidenceRow): string[] {
  const fromField = row.fieldHighlights?.[String(field)] ?? []
  if (fromField.length > 0) return fromField
  return String(row[field] || '')
    .split(/[;；,，。()\[\]\s]+/)
    .map((term) => term.trim())
    .filter((term) => term.length >= 5)
    .slice(0, 6)
}

function patientDisplayName(row: Pm3EvidenceRow, index: number): string {
  const source = [row.patientCount, row.patientAge, row.rawTableRow, row.sourceIndex].join(' ')
  const caseMatch = source.match(/\b(case|patient|proband|individual)\s*[-#:：]?\s*([A-Za-z0-9]+)\b/i)
  if (caseMatch) {
    const label = caseMatch[1].toLowerCase() === 'case' ? 'Case' : caseMatch[1][0].toUpperCase() + caseMatch[1].slice(1).toLowerCase()
    return `${label} ${caseMatch[2]}`
  }
  const chineseMatch = source.match(/(?:病例|患者|家系)\s*[-#:：]?\s*([A-Za-z0-9一二三四五六七八九十]+)/)
  if (chineseMatch) return `病例 ${chineseMatch[1]}`
  return `患者 ${index + 1}`
}

function pm3CellValue(row: Pm3EvidenceRow, column: keyof Pm3EvidenceRow, index: number): string {
  if (column === 'patientCount') return patientDisplayName(row, index)
  return String(row[column] || '')
}

function focusField(row: Pm3EvidenceRow, field: keyof Pm3EvidenceRow): void {
  const ids = fieldChunkIds(row, field)
  if (!ids.length) return
  revealSourceChunk(ids[0] || '', fieldTerms(row, field))
}

function focusFieldFromCell(row: Pm3EvidenceRow, field: keyof Pm3EvidenceRow, event: Event): void {
  const target = event.target
  if (target instanceof Element && target.closest('.field-citation')) return
  focusField(row, field)
}

function clearTermHighlights(): void {
  const root = sourceDocumentRef.value
  if (!root) return
  root.querySelectorAll('mark.field-term-highlight').forEach((mark) => {
    const text = document.createTextNode(mark.textContent || '')
    mark.replaceWith(text)
  })
  root.querySelectorAll('.chunk-highlight').forEach((el) => el.classList.remove('chunk-highlight', 'is-active'))
}

function highlightTerms(root: HTMLElement, terms: string[]): void {
  const validTerms = terms.map((term) => term.trim()).filter((term) => term.length >= 5).slice(0, 8)
  if (!validTerms.length) return
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (node instanceof Text && node.nodeValue?.trim()) textNodes.push(node)
  }
  for (const node of textNodes) {
    const text = node.nodeValue || ''
    const term = validTerms.find((item) => text.toLowerCase().includes(item.toLowerCase()))
    if (!term) continue
    const index = text.toLowerCase().indexOf(term.toLowerCase())
    const before = text.slice(0, index)
    const hit = text.slice(index, index + term.length)
    const after = text.slice(index + term.length)
    const mark = document.createElement('mark')
    mark.className = 'field-term-highlight'
    mark.textContent = hit
    node.replaceWith(document.createTextNode(before), mark, document.createTextNode(after))
  }
}

function cssEscape(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(value)
  return value.replace(/["\\]/g, '\\$&')
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

watch(activeChunkId, () => scrollSource())
watch(selectedVariant, (value) => {
  if (!value.trim()) pm3Sections.value = []
})
watch(documentMarkdown, () => {
  void nextTick(() => annotateBlocksByChunks())
})
watch([sourceViewMode, activeDocumentId], () => {
  if (sourceViewMode.value === 'pdf') void loadPdfPreview()
  if (sourceViewMode.value === 'markdown') void nextTick(() => annotateBlocksByChunks())
})
onMounted(() => {
  loadSettings()
  loadSourcePanelState()
  void loadDocumentList()
  void openRecordFromRoute()
  window.addEventListener('popstate', openRecordFromRoute)
  window.addEventListener('hashchange', handleSourceHashChange)
})
onUnmounted(() => {
  window.removeEventListener('popstate', openRecordFromRoute)
  window.removeEventListener('hashchange', handleSourceHashChange)
  stopSourcePanelResize()
  if (listPollTimer) window.clearInterval(listPollTimer)
})
</script>

<template>
  <div class="page">
    <nav class="top-tabs">
      <button type="button" class="top-tab" :class="{ active: currentView === 'tasks' }" @click="navigateTo('tasks')">解析任务</button>
      <button type="button" class="top-tab" :class="{ active: currentView === 'results' }" @click="navigateTo('results')">结构化结果 / PM3</button>
      <button type="button" class="top-tab" :class="{ active: currentView === 'settings' }" @click="navigateTo('settings')">模型设置</button>
    </nav>

    <main class="content">
      <section v-if="currentView === 'settings'" class="settings-page">
        <div class="page-title-row">
          <div>
            <h1>模型设置</h1>
            <p>保存 OpenAI-compatible 模型配置，供论文解析和 PM3 证据生成调用。</p>
          </div>
          <span class="status-chip" :class="{ ok: settingsSaved }">{{ settingsSaved ? '已保存' : '本地保存' }}</span>
        </div>
        <section class="settings-card">
          <label class="field-label">API URL</label>
          <input v-model="settings.apiUrl" class="text-input" placeholder="https://api.openai.com/v1" />
          <label class="field-label">Model Name</label>
          <input v-model="settings.modelName" class="text-input" placeholder="gpt-4o-mini" />
          <label class="field-label">API Key</label>
          <input v-model="settings.apiKey" class="text-input" type="password" placeholder="sk-..." />
          <button type="button" class="primary-action narrow" @click="saveSettings">保存设置</button>
        </section>
      </section>

      <section v-else-if="currentView === 'tasks'" class="tasks-page">
        <div class="page-title-row">
          <div>
            <h1>解析任务</h1>
            <p>批量上传 PDF / MinerU Markdown 后立即创建后台任务；文件保存到 S3，解析结果保存到 PostgreSQL。</p>
          </div>
          <button type="button" class="secondary-action" :disabled="listLoading" @click="loadDocumentList">
            {{ listLoading ? '刷新中...' : '刷新任务' }}
          </button>
        </div>
        <div v-if="storageMessage" class="notice-box">{{ storageMessage }}</div>

        <section class="task-submit-card">
          <div>
            <h2>提交解析</h2>
            <p>预处理阶段不输入变异位点；结构化结果页再输入 PM3 目标位点。</p>
          </div>
          <label class="upload-drop compact">
            <input :key="fileInputKey" type="file" accept=".pdf,.md,.markdown,.txt" multiple @change="handleFile" />
            <span class="upload-icon">PDF</span>
            <span>
              <strong>{{ selectedFilesLabel || '选择或拖入 PDF / Markdown 文件，可多选' }}</strong>
              <small>每个文件会创建一个独立后台任务，不阻塞列表、预览和删除等服务。</small>
            </span>
          </label>
          <div class="task-submit-actions">
            <div class="config-strip">
              <span>API URL: {{ settings.apiUrl || '未设置' }}</span>
              <span>Model: {{ settings.modelName || '未设置' }}</span>
              <button type="button" class="link-button" @click="navigateTo('settings')">修改设置</button>
            </div>
            <button type="button" class="primary-action large" :disabled="parsing" @click="parseMarkdown">
              {{ parsing ? '正在提交...' : '提交解析任务' }}
            </button>
          </div>
        </section>

        <section class="list-card">
          <div class="list-card-head">
            <div>
              <h2>任务列表</h2>
              <p>排队和解析中的任务会自动刷新状态。</p>
            </div>
            <span class="status-chip">{{ documentRecords.length }} 个任务</span>
          </div>
          <div v-if="listLoading" class="empty-state">正在加载任务列表...</div>
          <div v-else-if="!documentRecords.length" class="empty-state">暂无任务。请先上传 PDF / Markdown 并提交解析。</div>
          <table v-else class="data-table list-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>状态</th>
                <th>汇总行数</th>
                <th>候选变异</th>
                <th>S3 Key</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="record in documentRecords" :key="record.id">
                <td>{{ record.fileName }}</td>
                <td>
                  <span class="status-chip" :class="`status-${record.status}`">{{ statusLabel(record.status) }}</span>
                  <div v-if="record.status === 'failed' && record.errorMessage" class="error-text">{{ record.errorMessage }}</div>
                </td>
                <td>{{ isParsedRecord(record) ? pm3RowCount(record) : '-' }}</td>
                <td>{{ isParsedRecord(record) ? candidateCount(record) : '-' }}</td>
                <td>{{ record.s3Key }}</td>
                <td>{{ new Date(record.createdAt).toLocaleString() }}</td>
                <td>
                  <div class="row-actions">
                    <button type="button" class="link-button" :disabled="!isParsedRecord(record)" @click="openRecord(record)">
                      {{ isParsedRecord(record) ? '查看结果' : statusLabel(record.status) }}
                    </button>
                    <button
                      type="button"
                      class="link-button danger-link"
                      :disabled="deletingDocumentId === record.id"
                      @click="deleteRecord(record)"
                    >
                      {{ deletingDocumentId === record.id ? '删除中...' : '删除' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </section>

      <section v-else class="results-shell" :class="{ 'left-collapsed': leftPanelCollapsed, 'source-collapsed': sourcePanelCollapsed, resizing: resizingSourcePanel }" :style="resultsShellStyle">
        <aside class="material-panel" :class="{ collapsed: leftPanelCollapsed }">
          <button v-if="leftPanelCollapsed" type="button" class="left-rail" @click="setLeftPanelCollapsed(false)">
            <span>位点</span>
          </button>
          <div class="plan-overview-card">
            <div class="plan-overview-top">
              <div class="plan-overview-avatar">AI</div>
              <div>
                <div class="plan-overview-name">结构化解析结果</div>
                <div class="plan-overview-job">{{ uploadedFileName || '暂无已解析论文' }}</div>
              </div>
              <button type="button" class="panel-collapse-button" title="收起左侧面板" @click="setLeftPanelCollapsed(true)">收起</button>
            </div>
            <div class="plan-stat-row">
              <div v-for="stat in parseStats" :key="stat.label" class="plan-stat-box">
                <div class="plan-stat-num" :class="stat.className">{{ stat.value }}</div>
                <div class="plan-stat-label">{{ stat.label }}</div>
              </div>
            </div>
          </div>

          <div class="left-section">
            <div class="plan-section-head">
              <span>候选变异</span>
              <span class="plan-status-chip chip-draft">{{ candidates.length }}</span>
            </div>
            <button
              v-for="item in candidates"
              :key="item.variant"
              type="button"
              class="plan-timeline-file"
              :class="{ active: selectedVariant === item.variant }"
              @click="toggleCandidateVariant(item)"
            >
              <span class="plan-doc-type-tag">{{ item.gene }}</span>
                <span class="plan-timeline-info">
                  <span class="plan-timeline-filename">{{ item.variant }}</span>
                  <span class="plan-timeline-module">{{ item.protein }} · {{ item.patients }}</span>
                </span>
              </button>
            <div v-if="!candidates.length" class="plan-empty">暂无结果，请先提交解析任务。</div>

            <label class="field-label">输入 PM3 目标位点</label>
            <input v-model="selectedVariant" class="text-input compact" :disabled="!parsed" placeholder="NM_000155.4:c.821-7A>G" />
            <button type="button" class="primary-action danger" :disabled="!parsed || !selectedVariant.trim()" @click="runPm3">输出 PM3 结果</button>
          </div>
        </aside>

        <section class="result-panel">
          <div class="ailearn-detail-header">
            <div>
              <div class="ailearn-detail-title">论文结构化结果</div>
              <div class="ailearn-detail-meta">
                <span>按 GALT_c.821-7AG_PM3汇总.xlsx 字段展示</span>
              <span>{{ selectedPmid ? `PMID ${selectedPmid}` : '未选择 PMID' }}</span>
              <span>{{ selectedVariant || '未输入 PM3 位点' }}</span>
            </div>
          </div>
            <button type="button" class="ailearn-done-btn" @click="navigateTo('tasks')">返回任务</button>
          </div>
          <div v-if="storageMessage" class="result-notice">{{ storageMessage }}</div>

          <div v-if="!parsed" class="result-empty">
            <div class="empty-state">暂无已解析论文。请先到“解析任务”页面提交 PDF / Markdown 并等待结构化解析完成。</div>
            <button type="button" class="primary-action narrow" @click="navigateTo('tasks')">去提交任务</button>
          </div>

          <div v-else class="result-scroll">
            <section class="learn-section">
              <div class="learn-section-head">
                <div class="learn-section-left">
                  <span class="learn-section-index">1</span>
                  <span class="learn-section-title">文献信息</span>
                  <span class="ai-chip">Article</span>
                </div>
              </div>
              <div class="summary-grid article-grid">
                <button
                  v-for="field in ARTICLE_FIELDS"
                  :key="field.key"
                  type="button"
                  class="summary-card as-button"
                  :disabled="!articleRow"
                  @click="articleRow && focusField(articleRow, field.key)"
                >
                  <strong>{{ field.label }}</strong>
                  <span>{{ articleRow?.[field.key] || '未明确提及' }}</span>
                </button>
                <div class="summary-card">
                  <strong>当前 PM3 位点</strong>
                  <span>{{ selectedVariant || '未输入' }}</span>
                </div>
                <div class="summary-card">
                  <strong>候选变异</strong>
                  <span>{{ candidates.length }}</span>
                </div>
              </div>
            </section>

            <section class="learn-section">
              <div class="learn-section-head">
                <div class="learn-section-left">
                  <span class="learn-section-index">2</span>
                  <span class="learn-section-title">患者 / 病例维度 PM3 表</span>
                  <span class="ai-chip">Patient rows</span>
                  <span v-if="displayedRowNotice" class="ai-chip muted">{{ displayedRowNotice }}</span>
                </div>
              </div>
              <div class="wide-table-wrap">
                <table class="data-table pm3-summary-table" @click.capture="handleSummaryTableClick">
                  <thead>
                    <tr>
                      <th v-for="column in PM3_COLUMNS" :key="column.key">{{ column.label }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in displayedPm3Rows" :key="rowKey(row)" :class="{ active: selectedRowId === row.rowId }" @click="focusEvidenceRow(row)">
                      <td v-for="column in PM3_COLUMNS" :key="column.key" @click.stop="focusFieldFromCell(row, column.key, $event)">
                        <div>{{ pm3CellValue(row, column.key, rowIndex) }}</div>
                        <div class="field-citations">
                          <a
                            v-for="chunkId in fieldChunkIds(row, column.key)"
                            :key="`${rowKey(row)}-${String(column.key)}-${chunkId}`"
                            :href="`#${sourceAnchorId(chunkId)}`"
                            :data-source-id="chunkId"
                            class="field-citation"
                            @pointerdown.stop
                            @mousedown.stop
                            @click="focusCitation(chunkId, $event)"
                          >
                            {{ chunkId }}
                          </a>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section class="learn-section">
              <div class="learn-section-head">
                <div class="learn-section-left">
                  <span class="learn-section-index">3</span>
                  <span class="learn-section-title">字段复核</span>
                  <span class="ai-chip">人工审核</span>
                </div>
              </div>
              <article v-for="(row, rowIndex) in displayedPm3Rows" :key="`review-${rowKey(row)}`" class="knowledge-item" :class="{ active: selectedRowId === row.rowId }" @click="focusEvidenceRow(row)">
                <div class="knowledge-title-row">
                  <span class="knowledge-index">R</span>
                  <h3>PMID {{ row.pmid }} · {{ selectedVariant.trim() && rowMatchesVariant(row, selectedVariant) ? '命中当前位点' : '未判断目标位点' }}</h3>
                </div>
                <pre class="knowledge-visual">患者编号/病例: {{ patientDisplayName(row, rowIndex) }}
患者数/样本描述: {{ row.patientCount }}
家系情况: {{ row.familyInfo }}
关联合子状态: {{ row.zygosity }}
反式(trans)位点: {{ row.transVariant }}
顺式(cis)位点: {{ row.cisVariant }}
来源索引: {{ row.sourceIndex }}</pre>
              </article>
            </section>

            <section class="learn-section">
              <div class="learn-section-head">
                <div class="learn-section-left">
                  <span class="learn-section-index">4</span>
                  <span class="learn-section-title">PM3 输出</span>
                  <span class="ai-chip">Evidence</span>
                </div>
              </div>
              <div v-if="!pm3Sections.length" class="empty-state">在左侧输入目标位点后点击“输出 PM3 结果”。</div>
              <article v-for="section in pm3Sections" :key="section.title" class="pm3-card" :class="{ standard: section.tone === 'standard' }">
                <h3>{{ section.title }}</h3>
                <p>{{ section.body }}</p>
                <div class="citation-jumps">
                  <button v-for="sourceId in section.sourceIds" :key="sourceId" type="button" class="citation-jump" @click="focusSource(sourceId)">
                    {{ sourceId }}
                  </button>
                </div>
              </article>
            </section>
          </div>
        </section>

        <button
          v-if="!sourcePanelCollapsed"
          type="button"
          class="source-resizer"
          :class="{ active: resizingSourcePanel }"
          title="拖拽调整原文预览宽度"
          @mousedown.prevent="startSourcePanelResize"
          @dblclick="sourcePanelWidth = 560; persistSourcePanelState()"
        ></button>

        <aside class="source-panel" :class="{ collapsed: sourcePanelCollapsed }">
          <button v-if="sourcePanelCollapsed" type="button" class="source-rail" @click="setSourcePanelCollapsed(false)">
            <span>原文</span>
          </button>
          <div class="source-head">
            <div>
              <div class="source-title">原文</div>
              <div class="source-sub">{{ activeChunk?.title || '暂无来源' }} · {{ activeChunk?.reason || '点击结构化结果定位' }}</div>
            </div>
            <div class="source-tools">
              <button type="button" class="source-icon-button" title="收起原文预览" @click="setSourcePanelCollapsed(true)">收起</button>
              <div class="source-switch">
                <button type="button" :class="{ active: sourceViewMode === 'markdown' }" @click="setSourceViewMode('markdown')">Markdown</button>
                <button type="button" :class="{ active: sourceViewMode === 'pdf' }" @click="setSourceViewMode('pdf')">PDF</button>
              </div>
              <span class="source-count">{{ chunks.length }}</span>
            </div>
          </div>
          <div v-if="!parsed" class="empty-state">暂无原文。完成 Markdown 解析后，这里会显示可定位的原文片段。</div>
          <div v-else-if="sourceViewMode === 'pdf'" class="pdf-viewer">
            <div v-if="pdfPreviewLoading" class="empty-state">正在加载 PDF 预览...</div>
            <div v-else-if="pdfPreviewError" class="empty-state">{{ pdfPreviewError }}</div>
            <template v-else-if="pdfPreviewUrl">
              <div class="pdf-toolbar">
                <span>{{ uploadedFileName }}</span>
                <a :href="pdfPreviewUrl" target="_blank" rel="noreferrer">新窗口打开</a>
              </div>
              <iframe class="pdf-frame" :src="pdfPreviewUrl" :title="`${uploadedFileName} PDF 预览`"></iframe>
            </template>
          </div>
          <div v-else class="source-markdown-view">
            <section v-if="activeChunk" class="source-focus-card">
              <div class="source-focus-head">
                <strong>{{ activeChunk.id }}</strong>
                <span>{{ activeChunk.title }}</span>
              </div>
              <div class="source-focus-reason">{{ activeChunk.reason }}</div>
              <div class="source-focus-body markdown" v-html="renderActiveChunk()"></div>
            </section>
            <div ref="sourceDocumentRef" class="source-document markdown" v-html="renderDocument()"></div>
          </div>
        </aside>
      </section>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #fff; color: var(--n900); }
.top-tabs { height: 48px; display: flex; align-items: center; gap: 32px; padding: 0 32px; border-bottom: 1px solid var(--n100); }
.top-tab { height: 48px; display: flex; align-items: center; border: none; border-bottom: 2px solid transparent; background: transparent; color: var(--n500); font-size: 15px; cursor: pointer; }
.top-tab.active { border-color: var(--primary-500); color: var(--n900); font-weight: 700; }
.content { padding: 24px 32px; }
.tasks-page { max-width: 1180px; margin: 0 auto; display: grid; gap: 16px; }
.upload-page { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 24px; height: calc(100vh - 96px); }
.results-shell { display: grid; gap: 16px; height: calc(100vh - 96px); position: relative; }
.results-shell > * { min-height: 0; }
.results-shell.resizing { user-select: none; cursor: col-resize; }
.material-panel, .result-panel, .source-panel, .settings-card, .upload-main { border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; overflow: hidden; }
.material-panel { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.material-panel.collapsed { border-style: dashed; background: #f8fafc; }
.material-panel.collapsed .plan-overview-card,
.material-panel.collapsed .left-section { display: none; }
.left-rail { width: 100%; height: 100%; border: none; background: transparent; color: #15803d; font-size: 12px; font-weight: 900; cursor: pointer; writing-mode: vertical-rl; letter-spacing: 0; display: flex; align-items: center; justify-content: center; }
.left-rail:hover { background: #f0fdf4; }
.settings-page, .list-page { max-width: 1180px; margin: 0 auto; }
.page-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.page-title-row h1 { margin: 0; font-size: 22px; line-height: 1.35; }
.page-title-row p { margin: 6px 0 0; color: #64748b; font-size: 13px; line-height: 1.7; }
.settings-card { padding: 20px; }
.list-card { border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; overflow: auto; }
.list-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 18px; border-bottom: 1px solid #e2e8f0; }
.list-card-head h2, .task-submit-card h2 { margin: 0; font-size: 16px; line-height: 1.4; color: #0f172a; }
.list-card-head p, .task-submit-card p { margin: 4px 0 0; color: #64748b; font-size: 12.5px; line-height: 1.6; }
.task-submit-card { border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; padding: 18px; display: grid; grid-template-columns: 240px minmax(360px, 1fr) minmax(220px, 280px); gap: 18px; align-items: center; }
.task-submit-actions { min-width: 0; display: grid; gap: 12px; align-content: center; }
.notice-box { margin: 12px 0; border: 1px solid #bfdbfe; border-radius: 10px; background: #eff6ff; color: #1d4ed8; padding: 10px 12px; font-size: 13px; line-height: 1.6; }
.result-notice { margin: 12px 16px 0; border: 1px solid #bfdbfe; border-radius: 10px; background: #eff6ff; color: #1d4ed8; padding: 9px 12px; font-size: 12.5px; line-height: 1.55; }
.status-chip, .plan-status-chip { border-radius: 999px; background: #f1f5f9; color: #64748b; padding: 4px 10px; font-size: 11px; font-weight: 800; white-space: nowrap; }
.status-chip.ok, .chip-published { background: #dcfce7; color: #15803d; }
.status-chip.status-queued { background: #e0f2fe; color: #0369a1; }
.status-chip.status-processing { background: #fef9c3; color: #854d0e; }
.status-chip.status-parsed { background: #dcfce7; color: #15803d; }
.status-chip.status-failed { background: #fee2e2; color: #b91c1c; }
.error-text { max-width: 280px; margin-top: 6px; color: #b91c1c; font-size: 11px; line-height: 1.45; white-space: normal; }
.chip-draft { background: #fef9c3; color: #854d0e; }
.field-label { display: block; color: #64748b; font-size: 12px; font-weight: 800; margin: 12px 0 6px; }
.text-input { width: 100%; border: 1px solid #e2e8f0; border-radius: 9px; padding: 10px 12px; color: #1e293b; outline: none; }
.text-input.compact { padding: 9px 10px; }
.text-input:focus { border-color: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,0.08); }
.text-input:disabled { background: #f8fafc; color: #94a3b8; cursor: not-allowed; }
.primary-action, .secondary-action, .ailearn-done-btn { border: none; border-radius: 9px; background: #22c55e; color: #fff; padding: 10px 12px; font-weight: 850; cursor: pointer; }
.primary-action:disabled { opacity: 0.45; cursor: not-allowed; }
.primary-action.narrow { width: 160px; margin-top: 18px; }
.primary-action.large { width: 100%; min-width: 0; margin-top: 0; }
.primary-action.danger { width: 100%; margin-top: 10px; background: #ef4444; }
.secondary-action { background: #fff; color: #15803d; border: 1px solid #bbf7d0; }
.link-button { border: none; background: transparent; color: #15803d; font-weight: 800; cursor: pointer; }
.link-button:disabled { color: #94a3b8; cursor: not-allowed; }
.danger-link { color: #dc2626; }
.row-actions { display: inline-flex; align-items: center; gap: 10px; white-space: nowrap; }
.plan-overview-card { margin: 12px; background: linear-gradient(135deg, #f0fdf4, #dcfce7); border: 1px solid #bbf7d0; border-radius: 12px; padding: 12px; flex-shrink: 0; }
.plan-overview-top { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 10px; margin-bottom: 10px; }
.plan-overview-avatar { width: 34px; height: 34px; border-radius: 999px; background: linear-gradient(135deg, #4ade80, #16a34a); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 12px; font-weight: 800; flex-shrink: 0; }
.plan-overview-name { font-size: 14px; font-weight: 800; color: #0f172a; }
.plan-overview-job { margin-top: 2px; font-size: 11.5px; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.panel-collapse-button { border: 1px solid #bbf7d0; border-radius: 999px; background: #fff; color: #15803d; padding: 4px 8px; font-size: 11px; font-weight: 850; cursor: pointer; flex-shrink: 0; }
.panel-collapse-button:hover { background: #f0fdf4; }
.plan-stat-row { display: flex; gap: 10px; }
.plan-stat-box { flex: 1; min-width: 0; background: #fff; border-radius: 8px; padding: 7px 5px; text-align: center; border: 1px solid #e2e8f0; }
.plan-stat-num { font-size: 18px; font-weight: 900; color: #0f172a; line-height: 1; }
.plan-stat-num.done { color: #16a34a; }
.plan-stat-num.progress { color: #1d4ed8; }
.plan-stat-num.todo { color: #6b7280; }
.plan-stat-label { font-size: 10.5px; color: #94a3b8; margin-top: 3px; }
.plan-progress-bar { height: 7px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin: 8px 0 4px; }
.plan-progress-fill { height: 100%; background: linear-gradient(90deg, #4ade80, #16a34a); border-radius: 999px; transition: width 0.4s ease; }
.plan-progress-text { display: block; font-size: 11px; color: #15803d; text-align: right; }
.upload-main { padding: 24px; }
.upload-drop { min-height: 220px; border: 1px dashed #cbd5e1; border-radius: 12px; background: #f8fafc; display: flex; align-items: center; justify-content: center; gap: 16px; cursor: pointer; }
.upload-drop.compact { min-height: 96px; justify-content: flex-start; padding: 14px 16px; }
.upload-drop input { display: none; }
.upload-icon { width: 48px; height: 48px; border-radius: 12px; background: #dcfce7; color: #15803d; display: flex; align-items: center; justify-content: center; font-weight: 900; }
.upload-drop strong { display: block; color: #0f172a; font-size: 15px; }
.upload-drop small { display: block; margin-top: 4px; color: #64748b; }
.config-strip { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.75fr) auto; align-items: center; gap: 10px; color: #64748b; font-size: 12px; }
.config-strip span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.config-strip .link-button { white-space: nowrap; }
.left-section { flex: 1; min-height: 0; padding: 0 12px 14px; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.left-section::-webkit-scrollbar { width: 8px; }
.left-section::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 999px; border: 2px solid #fff; }
.left-section::-webkit-scrollbar-track { background: transparent; }
.plan-section-head { display: flex; align-items: center; justify-content: space-between; font-size: 13px; font-weight: 800; color: #0f172a; margin: 8px 0 12px; }
.plan-timeline-file { width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 9px; margin-bottom: 6px; border: 1px solid #e2e8f0; border-radius: 9px; background: #fff; text-align: left; cursor: pointer; transition: all 0.15s; }
.plan-timeline-file:hover, .plan-timeline-file.active { border-color: #22c55e; background: #f0fdf4; }
.plan-doc-type-tag { padding: 2px 6px; border-radius: 5px; font-size: 9.5px; font-weight: 900; background: #f1f5f9; color: #475569; flex-shrink: 0; }
.plan-timeline-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.plan-timeline-filename { font-weight: 700; color: #0f172a; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.plan-timeline-module { color: #94a3b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.plan-empty, .empty-state { padding: 24px 16px; text-align: center; color: #94a3b8; font-size: 13px; line-height: 1.7; }
.ailearn-detail-header { padding: 14px 18px; border-bottom: 1px solid #f1f3f1; background: #fafbfa; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ailearn-detail-title { color: #0f172a; font-size: 14px; font-weight: 800; }
.ailearn-detail-meta { margin-top: 4px; display: flex; align-items: center; gap: 12px; color: #64748b; font-size: 12px; flex-wrap: wrap; }
.result-scroll { height: calc(100% - 69px); overflow-y: auto; padding: 16px; }
.result-panel:has(.result-notice) .result-scroll { height: calc(100% - 122px); }
.result-empty { height: calc(100% - 69px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 24px; }
.learn-section { padding-bottom: 18px; margin-bottom: 18px; border-bottom: 1px solid var(--n100); }
.learn-section:last-child { border-bottom: none; }
.learn-section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.learn-section-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.learn-section-index { width: 22px; height: 22px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; background: var(--n900); color: #fff; font-size: 12px; font-weight: 800; flex-shrink: 0; }
.learn-section-title { color: var(--n900); font-size: 14px; font-weight: 800; white-space: nowrap; }
.ai-chip { border-radius: 999px; background: var(--primary-100); color: var(--primary-800); padding: 3px 8px; font-size: 11px; font-weight: 800; white-space: nowrap; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.summary-grid.article-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.summary-card { border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; padding: 12px; }
.summary-card.as-button { text-align: left; cursor: pointer; }
.summary-card.as-button:hover { border-color: #22c55e; background: #f0fdf4; }
.summary-card.as-button:disabled { cursor: default; opacity: 0.65; }
.summary-card strong { display: block; color: #64748b; font-size: 11px; margin-bottom: 6px; }
.summary-card span { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; color: #0f172a; font-size: 13px; font-weight: 800; line-height: 1.55; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.data-table th, .data-table td { border: 1px solid #e2e8f0; padding: 9px 10px; text-align: left; vertical-align: top; }
.data-table th { background: #f8fafc; color: #475569; }
.data-table tr { cursor: pointer; }
.data-table tr:hover td { background: #f0fdf4; }
.data-table tr.active td { background: #dcfce7; }
.list-table { min-width: 980px; }
.list-table th, .list-table td { white-space: nowrap; }
.list-table td:nth-child(1), .list-table td:nth-child(5) { max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
.wide-table-wrap { width: 100%; overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 10px; }
.pm3-summary-table { min-width: 1900px; border: none; }
.pm3-summary-table th { min-width: 120px; white-space: normal; line-height: 1.45; }
.pm3-summary-table td { min-width: 140px; max-width: 260px; line-height: 1.55; }
.pm3-summary-table th:nth-child(4), .pm3-summary-table td:nth-child(4),
.pm3-summary-table th:nth-child(11), .pm3-summary-table td:nth-child(11),
.pm3-summary-table th:nth-child(12), .pm3-summary-table td:nth-child(12) { min-width: 300px; max-width: 420px; }
.field-citations { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
.field-citation { display: inline-flex; align-items: center; border: 1px solid #bbf7d0; border-radius: 999px; background: #f0fdf4; color: #15803d; padding: 2px 6px; font-size: 10.5px; font-weight: 850; cursor: pointer; text-decoration: none; }
.field-citation:hover { border-color: #22c55e; background: #dcfce7; }
.knowledge-item, .pm3-card { border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; overflow: hidden; margin-bottom: 10px; }
.knowledge-item.active { border-color: #22c55e; background: #f0fdf4; }
.knowledge-title-row { display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; }
.knowledge-index { width: 20px; height: 20px; border: 1px solid var(--primary-500); border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; color: var(--primary-700); background: var(--primary-50); font-size: 11px; font-weight: 800; flex-shrink: 0; margin-top: 1px; }
.knowledge-item h3, .pm3-card h3 { margin: 0; color: #0f172a; font-size: 13px; font-weight: 800; line-height: 1.55; }
.knowledge-visual { margin: 0 14px 12px; border: 1px solid var(--primary-100); border-radius: 8px; background: var(--primary-50); color: var(--primary-800); padding: 11px 14px; font-family: inherit; font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-x: auto; }
.pm3-card { padding: 12px 14px; }
.pm3-card.standard { border-left: 5px solid #2563eb; background: #eff6ff; }
.pm3-card p { color: #334155; font-size: 13px; line-height: 1.7; margin: 8px 0 12px; }
.citation-jumps { display: flex; flex-wrap: wrap; gap: 6px; }
.citation-jump { border: 1px solid #bbf7d0; border-radius: 999px; background: #f0fdf4; color: #15803d; padding: 3px 8px; font-size: 12px; font-weight: 800; cursor: pointer; }
.source-resizer { position: relative; width: 8px; height: 100%; margin: 0 -12px 0 -12px; border: none; border-radius: 999px; background: transparent; cursor: col-resize; z-index: 4; }
.source-resizer::before { content: ""; position: absolute; top: 12px; bottom: 12px; left: 3px; width: 2px; border-radius: 999px; background: #cbd5e1; transition: background 0.15s, box-shadow 0.15s; }
.source-resizer:hover::before, .source-resizer.active::before { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12); }
.source-panel { display: flex; flex-direction: column; min-width: 0; position: relative; }
.source-panel.collapsed { align-items: stretch; justify-content: stretch; border-style: dashed; background: #f8fafc; }
.source-panel.collapsed .source-head,
.source-panel.collapsed .empty-state,
.source-panel.collapsed .pdf-viewer,
.source-panel.collapsed .source-markdown-view,
.source-panel.collapsed .source-document { display: none; }
.source-rail { width: 100%; height: 100%; border: none; background: transparent; color: #15803d; font-size: 12px; font-weight: 900; cursor: pointer; writing-mode: vertical-rl; letter-spacing: 0; display: flex; align-items: center; justify-content: center; }
.source-rail:hover { background: #f0fdf4; }
.source-head { padding: 15px 16px; border-bottom: 1px solid #f1f3f1; background: #fafbfa; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.source-title { font-size: 15px; font-weight: 800; color: #0f172a; }
.source-sub { margin-top: 3px; color: #64748b; font-size: 12px; }
.source-tools { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.source-icon-button { border: 1px solid #e2e8f0; border-radius: 999px; background: #fff; color: #64748b; padding: 4px 8px; font-size: 12px; font-weight: 800; cursor: pointer; }
.source-icon-button:hover { border-color: #bbf7d0; color: #15803d; background: #f0fdf4; }
.source-switch { display: inline-flex; padding: 3px; border: 1px solid #e2e8f0; border-radius: 999px; background: #fff; gap: 2px; }
.source-switch button { border: none; border-radius: 999px; background: transparent; color: #64748b; padding: 4px 9px; font-size: 12px; font-weight: 800; cursor: pointer; }
.source-switch button.active { background: #dcfce7; color: #15803d; }
.source-count { min-width: 28px; height: 24px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; background: #dcfce7; color: #15803d; font-size: 12px; font-weight: 800; }
.pdf-viewer { position: relative; flex: 1; min-height: 0; background: #f8fafc; display: flex; flex-direction: column; }
.pdf-toolbar { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 12px; border-bottom: 1px solid #e2e8f0; background: #fff; color: #475569; font-size: 12px; font-weight: 800; }
.pdf-toolbar span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pdf-toolbar a { color: #15803d; text-decoration: none; white-space: nowrap; }
.pdf-frame { flex: 1; min-height: 0; width: 100%; border: none; background: #fff; }
.source-markdown-view { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
.source-focus-card { flex-shrink: 0; max-height: 260px; overflow: auto; border-bottom: 1px solid #e2e8f0; background: #fff7ed; padding: 12px 14px; }
.source-focus-head { display: flex; align-items: center; gap: 8px; color: #0f172a; font-size: 12px; font-weight: 850; }
.source-focus-head strong { border-radius: 999px; background: #fed7aa; color: #9a3412; padding: 2px 8px; font-size: 11px; }
.source-focus-head span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-focus-reason { margin-top: 5px; color: #9a3412; font-size: 11.5px; line-height: 1.5; }
.source-focus-body { margin-top: 8px; border: 1px solid #fed7aa; border-radius: 8px; background: #fff; padding: 10px; color: #334155; font-size: 12.5px; line-height: 1.7; }
.source-focus-body :deep(table) { width: 100%; border-collapse: collapse; margin: 0; font-size: 12px; }
.source-focus-body :deep(th), .source-focus-body :deep(td) { border: 1px solid #e2e8f0; padding: 7px 8px; text-align: left; vertical-align: top; }
.source-focus-body :deep(th) { background: #ffedd5; color: #0f172a; font-weight: 800; }
.source-focus-body :deep(p) { margin: 0 0 8px; }
.source-focus-body :deep(p:last-child) { margin-bottom: 0; }
.source-document { flex: 1; min-height: 0; overflow-y: auto; padding: 28px 32px 64px; background: #fff; color: #334155; font-size: 14.5px; line-height: 1.85; scroll-behavior: auto; }
.source-document > :deep(*) { max-width: 960px; margin-left: auto; margin-right: auto; }
.source-document :deep(h1) { text-align: center; color: #333; font-size: 26px; font-weight: 800; margin: 28px auto 22px; line-height: 1.4; }
.source-document :deep(h2) { color: #222; font-size: 20px; font-weight: 700; margin: 32px auto 14px; padding-bottom: 8px; border-bottom: 1px solid #f1f5f9; line-height: 1.45; }
.source-document :deep(h3) { color: #1f2937; font-size: 17px; font-weight: 700; margin: 24px auto 10px; }
.source-document :deep(h4) { color: #334155; font-size: 15px; font-weight: 700; margin: 20px auto 8px; }
.source-document :deep(h5), .source-document :deep(h6) { color: #475569; font-size: 14px; font-weight: 700; margin: 16px auto 6px; }
.source-document :deep(p) { margin: 0 auto 14px; color: #334155; }
.source-document :deep(ul), .source-document :deep(ol) { margin: 8px auto 14px; padding-left: 24px; }
.source-document :deep(li) { margin: 4px 0; }
.source-document :deep(strong) { color: #0f172a; font-weight: 800; }
.source-document :deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; border: 1px solid #e2e8f0; border-radius: 6px; background: #f8fafc; padding: 1px 6px; font-size: 13px; color: #0f172a; }
.source-document :deep(pre) { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; padding: 14px 16px; margin: 14px auto; }
.source-document :deep(pre code) { border: none; background: transparent; padding: 0; }
.source-document :deep(table) { width: 100%; border-collapse: collapse; margin: 14px auto; font-size: 13px; }
.source-document :deep(th), .source-document :deep(td) { border: 1px solid #e2e8f0; padding: 8px 10px; vertical-align: top; text-align: left; }
.source-document :deep(th) { background: #f8fafc; font-weight: 700; color: #0f172a; }
.source-document :deep(table[data-table-source]) { position: relative; }
.source-document :deep(table.chunk-highlight) { outline: 3px solid #f59e0b; outline-offset: 4px; background: #fffbeb; box-shadow: 0 0 0 7px rgba(245, 158, 11, 0.16); }
.source-document :deep(table.chunk-highlight th) { background: #fef3c7; }
.source-document :deep(table.chunk-highlight td) { background: #fffbeb; }
.source-document :deep(table.is-active) { outline-color: #ea580c; box-shadow: 0 0 0 7px rgba(234, 88, 12, 0.2); }
.source-document :deep(blockquote) { margin: 14px auto; padding: 10px 16px; background: #f8fafc; border-left: 3px solid #94a3b8; color: #64748b; border-radius: 0 6px 6px 0; }
.source-document :deep(hr) { border: none; border-top: 1px solid #e2e8f0; margin: 28px auto; }
.source-document :deep(.page-marker) { display: block; text-align: center; color: #94a3b8; font-size: 12px; font-weight: 700; letter-spacing: 0.12em; margin: 32px auto; }
.source-document :deep(.page-marker)::before, .source-document :deep(.page-marker)::after { content: ""; display: inline-block; width: 60px; height: 1px; background: #e2e8f0; vertical-align: middle; margin: 0 14px; }
.source-document :deep(.chunk-highlight) { background: #fef9c3; border-radius: 4px; box-shadow: inset 0 0 0 1px rgba(253, 224, 71, 0.4); scroll-margin-top: 80px; transition: background 0.2s, box-shadow 0.2s; }
.source-document :deep(.chunk-highlight.is-active) { background: #fde047; box-shadow: inset 0 0 0 1px rgba(202, 138, 4, 0.6), 0 0 0 3px rgba(253, 224, 71, 0.25); }
.source-document :deep(.field-term-highlight) { background: #fb923c; color: #111827; border-radius: 3px; padding: 0 2px; }
.source-document :deep(.source-empty) { max-width: 560px; margin: 80px auto 0; color: #94a3b8; text-align: center; font-size: 13px; line-height: 1.8; }
.source-document :deep(.source-chunk-document) { max-width: 960px; margin: 0 auto; }
.source-document :deep(.chunk-card) { border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; margin: 0 auto 14px; overflow: hidden; scroll-margin-top: 80px; }
.source-document :deep(.chunk-card.active) { border-color: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.09); }
.source-document :deep(.chunk-card-head) { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; color: #0f172a; font-size: 13px; font-weight: 850; }
.source-document :deep(.chunk-card-head strong) { color: #15803d; font-size: 11px; white-space: nowrap; }
.source-document :deep(.chunk-card-reason) { padding: 10px 12px 0; color: #64748b; font-size: 12px; line-height: 1.7; }
.source-document :deep(.chunk-card-quote) { margin: 10px 12px 12px; border: 1px solid #dcfce7; border-radius: 8px; background: #f0fdf4; color: #334155; padding: 12px; font-family: inherit; font-size: 12.5px; line-height: 1.75; white-space: pre-wrap; overflow-x: auto; }
@media (max-width: 1100px) {
  body { min-width: 0; }
  .task-submit-card { grid-template-columns: 1fr; }
  .config-strip { grid-template-columns: 1fr; align-items: flex-start; }
  .upload-page { grid-template-columns: 1fr; height: auto; }
  .results-shell { height: calc(100vh - 96px); }
  .source-panel, .material-panel, .result-panel { min-height: 420px; }
}
</style>
