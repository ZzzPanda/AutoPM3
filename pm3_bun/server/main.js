import { config as loadDotenv } from 'dotenv';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { Worker } from 'node:worker_threads';
import Fastify from 'fastify';
import postgres from 'postgres';
import { z } from 'zod';
import { DeleteObjectCommand, GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { PDFParse } from 'pdf-parse';

if (existsSync('server/.env')) {
  loadDotenv({ path: 'server/.env' });
} else {
  loadDotenv();
}

const envSchema = z.object({
  PORT: z.coerce.number().default(3017),
  HOST: z.string().default('0.0.0.0'),
  DATABASE_URL: z.string().optional(),
  S3_ENDPOINT: z.string().optional(),
  S3_REGION: z.string().default('us-east-1'),
  S3_ACCESS_KEY: z.string().optional(),
  S3_SECRET_KEY: z.string().optional(),
  S3_BUCKET: z.string().optional(),
  MINERU_SERVICE_URL: z.string().optional(),
  MINERU_SERVICE_BACKEND: z.string().default('vlm-vllm-async-engine'),
  MINERU_SERVICE_TIMEOUT: z.coerce.number().optional(),
  MINERU_TIMEOUT_MS: z.coerce.number().default(540000),
  TASK_WORKER_CONCURRENCY: z.coerce.number().default(2),
});

const env = envSchema.parse(process.env);

const UploadSchema = z.object({
  fileName: z.string().min(1),
  mimeType: z.string().min(1),
  data: z.string().min(1),
  hash: z.string().regex(/^[a-fA-F0-9]{64}$/),
  modelSettings: z
    .object({
      apiUrl: z.string().min(1),
      modelName: z.string().min(1),
      apiKey: z.string().min(1),
    })
    .optional(),
  parsedResult: z.unknown().optional(),
});

const ParsedResultSchema = z.object({
  candidates: z.array(
    z.object({
      variant: z.string(),
      protein: z.string(),
      gene: z.string(),
      patients: z.string(),
      context: z.string(),
      partner: z.string(),
      source: z.string(),
    }),
  ),
  pm3Rows: z.array(
    z.object({
      pmid: z.string(),
      title: z.string(),
      authors: z.string(),
      patientCount: z.string(),
      patientAge: z.string(),
      clinicalDisease: z.string(),
      clinicalPhenotype: z.string(),
      familyInfo: z.string(),
      pathogenicity: z.string(),
      zygosity: z.string(),
      transVariant: z.string(),
      cisVariant: z.string(),
      sourceIndex: z.string(),
      rawTableRow: z.string(),
      literatureBackground: z.string(),
      summary: z.string(),
      extractionProcess: z.string(),
      source: z.string(),
      fieldSources: z.record(z.string(), z.array(z.string())).optional(),
      fieldHighlights: z.record(z.string(), z.array(z.string())).optional(),
    }),
  ),
  chunks: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      reason: z.string(),
      quote: z.string(),
      startOffset: z.number().optional(),
      endOffset: z.number().optional(),
      evidenceTerms: z.array(z.string()).optional(),
    }),
  ),
  documentMarkdown: z.string().optional(),
  selectedVariant: z.string(),
});

function requireStorageEnv() {
  const missing = [];
  if (!env.DATABASE_URL) missing.push('DATABASE_URL');
  if (!env.S3_ACCESS_KEY) missing.push('S3_ACCESS_KEY');
  if (!env.S3_SECRET_KEY) missing.push('S3_SECRET_KEY');
  if (!env.S3_BUCKET) missing.push('S3_BUCKET');
  if (missing.length > 0) {
    const err = new Error(`Missing storage environment: ${missing.join(', ')}`);
    err.statusCode = 503;
    throw err;
  }
}

const sql = env.DATABASE_URL ? postgres(env.DATABASE_URL) : null;
const s3Client =
  env.S3_ACCESS_KEY && env.S3_SECRET_KEY
    ? new S3Client({
        region: env.S3_REGION,
        endpoint: env.S3_ENDPOINT,
        credentials: {
          accessKeyId: env.S3_ACCESS_KEY,
          secretAccessKey: env.S3_SECRET_KEY,
        },
        forcePathStyle: Boolean(env.S3_ENDPOINT),
      })
    : null;

async function migrate() {
  if (!sql) return;
  await sql`
    create table if not exists autopm3_documents (
      id varchar(255) primary key,
      file_name varchar(1024) not null,
      mime_type varchar(255) not null,
      file_hash varchar(64) not null,
      s3_key varchar(2048) not null,
      status varchar(64) not null default 'parsed',
      parsed_result jsonb not null,
      error_message text,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `;
  await sql`alter table autopm3_documents alter column parsed_result set default '{}'::jsonb`;
  await sql`alter table autopm3_documents add column if not exists error_message text`;
  await sql`create index if not exists autopm3_documents_created_at_idx on autopm3_documents(created_at desc)`;
  await sql`create index if not exists autopm3_documents_status_idx on autopm3_documents(status)`;
}

function rowToDocument(row) {
  return {
    id: row.id,
    fileName: row.file_name,
    mimeType: row.mime_type,
    fileHash: row.file_hash,
    s3Key: row.s3_key,
    status: row.status,
    parsedResult: row.parsed_result,
    errorMessage: row.error_message,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

const taskQueue = [];
const activeTaskIds = new Set();
const workerUrl = new URL('./pm3-worker.js', import.meta.url);

function enqueueParseTask(task) {
  taskQueue.push(task);
  drainTaskQueue();
}

function drainTaskQueue() {
  if (!sql) return;
  while (activeTaskIds.size < env.TASK_WORKER_CONCURRENCY && taskQueue.length > 0) {
    const task = taskQueue.shift();
    if (!task || activeTaskIds.has(task.id)) continue;
    activeTaskIds.add(task.id);
    const worker = new Worker(workerUrl, {
      workerData: {
        ...task,
        env: {
          DATABASE_URL: env.DATABASE_URL,
          S3_ENDPOINT: env.S3_ENDPOINT,
          S3_REGION: env.S3_REGION,
          S3_ACCESS_KEY: env.S3_ACCESS_KEY,
          S3_SECRET_KEY: env.S3_SECRET_KEY,
          S3_BUCKET: env.S3_BUCKET,
          MINERU_SERVICE_URL: env.MINERU_SERVICE_URL,
          MINERU_SERVICE_BACKEND: env.MINERU_SERVICE_BACKEND,
          MINERU_SERVICE_TIMEOUT: env.MINERU_SERVICE_TIMEOUT,
          MINERU_TIMEOUT_MS: env.MINERU_TIMEOUT_MS,
        },
      },
    });
    worker.once('message', (message) => {
      if (message?.ok) app.log.info({ documentId: task.id }, 'PM3 parse worker finished');
      else app.log.error({ documentId: task.id, error: message?.error }, 'PM3 parse worker failed');
    });
    worker.once('error', async (err) => {
      app.log.error({ documentId: task.id, err }, 'PM3 parse worker crashed');
      try {
        await sql`
          update autopm3_documents
          set status = 'failed', error_message = ${err.message}, updated_at = now()
          where id = ${task.id}
        `;
      } catch (updateErr) {
        app.log.error({ documentId: task.id, err: updateErr }, 'failed to persist worker crash');
      }
    });
    worker.once('exit', (code) => {
      activeTaskIds.delete(task.id);
      if (code !== 0) app.log.error({ documentId: task.id, code }, 'PM3 parse worker exited non-zero');
      drainTaskQueue();
    });
  }
}

function normalizeApiUrl(apiUrl) {
  return apiUrl.replace(/\/+$/, '');
}

async function extractText(buffer, mimeType, fileName) {
  const lowerName = fileName.toLowerCase();
  if (mimeType.includes('pdf') || lowerName.endsWith('.pdf')) {
    if (env.MINERU_SERVICE_URL) {
      return parsePdfWithMineru(buffer, fileName, mimeType);
    }
    const parser = new PDFParse({ data: buffer });
    try {
      const parsed = await parser.getText();
      return parsed.text || '';
    } finally {
      await parser.destroy();
    }
  }
  return buffer.toString('utf8');
}

function pickMineruResult(raw, fileName) {
  const results = raw?.results;
  if (!results || typeof results !== 'object') return null;
  const stem = fileName.replace(/\.[^./]+$/, '');
  if (Object.hasOwn(results, fileName)) return results[fileName];
  if (Object.hasOwn(results, stem)) return results[stem];
  return Object.values(results)[0] || null;
}

function renderMarkdownFromMineruMiddleJson(middleJson) {
  const pdfInfo = middleJson?.pdf_info;
  if (!Array.isArray(pdfInfo) || pdfInfo.length === 0) return '';
  return [...pdfInfo]
    .sort((a, b) => (a?.page_idx ?? 0) - (b?.page_idx ?? 0))
    .map((page) => {
      const pageNumber = Number.isInteger(page?.page_idx) ? page.page_idx + 1 : 0;
      const blocks = [...(Array.isArray(page?.para_blocks) ? page.para_blocks : []), ...(Array.isArray(page?.discarded_blocks) ? page.discarded_blocks : [])];
      const content = blocks.map(renderMineruBlock).filter(Boolean).join('\n\n');
      return `<!-- page: ${pageNumber} -->\n${content}`.trim();
    })
    .filter(Boolean)
    .join('\n\n');
}

function renderMineruBlock(block) {
  if (!block || typeof block !== 'object') return '';
  if (Array.isArray(block.blocks)) {
    const nested = block.blocks.map(renderMineruBlock).filter(Boolean).join('\n\n');
    if (block.type === 'title' || block.type === 'header') return nested ? `# ${nested.replace(/^#+\s*/, '').trim()}` : '';
    return nested;
  }
  if (Array.isArray(block.lines)) {
    const text = block.lines.flatMap((line) => (Array.isArray(line?.spans) ? line.spans : [])).map((span) => span?.html || span?.content || span?.text || '').join('').trim();
    if (!text) return '';
    if (block.type === 'title' || block.type === 'header') return `# ${text.replace(/^#+\s*/, '').trim()}`;
    return text;
  }
  return '';
}

async function parsePdfWithMineru(buffer, fileName, mimeType) {
  const form = new FormData();
  form.append('files', new Blob([new Uint8Array(buffer)], { type: mimeType || 'application/pdf' }), fileName);
  form.append('return_middle_json', 'true');
  form.append('return_md', 'true');
  form.append('output_dir', './output');
  form.append('backend', env.MINERU_SERVICE_BACKEND);

  const response = await fetch(env.MINERU_SERVICE_URL, {
    method: 'POST',
    body: form,
    signal: AbortSignal.timeout(env.MINERU_SERVICE_TIMEOUT || env.MINERU_TIMEOUT_MS),
  });
  if (!response.ok) {
    const detail = await response.text();
    const err = new Error(`MinerU request failed (${response.status}): ${detail.slice(0, 1000)}`);
    err.statusCode = 502;
    throw err;
  }
  const raw = await response.json();
  const result = pickMineruResult(raw, fileName);
  if (!result || typeof result !== 'object') {
    const err = new Error('MinerU response did not contain parse results');
    err.statusCode = 502;
    throw err;
  }
  let markdown = typeof result.md_content === 'string' ? result.md_content : '';
  if (typeof result.middle_json === 'string') {
    try {
      const rendered = renderMarkdownFromMineruMiddleJson(JSON.parse(result.middle_json));
      if (rendered.trim()) markdown = rendered;
    } catch {
      // Keep md_content when middle_json rendering fails.
    }
  }
  if (!markdown.trim()) {
    const err = new Error('MinerU returned empty markdown');
    err.statusCode = 502;
    throw err;
  }
  return markdown;
}

function truncateForModel(text, maxChars = 70000) {
  if (text.length <= maxChars) return text;
  const head = text.slice(0, Math.floor(maxChars * 0.72));
  const tail = text.slice(text.length - Math.floor(maxChars * 0.28));
  return `${head}\n\n...[TRUNCATED MIDDLE]...\n\n${tail}`;
}

function compactText(text) {
  return text.replace(/\s+/g, ' ').trim().toLowerCase();
}

function createTableEvidenceChunks(text) {
  const chunks = [];
  const addTable = (quote, start, end, label) => {
    const normalized = quote.trim();
    if (normalized.length < 40) return;
    chunks.push({
      id: `table-${chunks.length + 1}`,
      title: `表格 ${chunks.length + 1}`,
      reason: `${label}，字符 ${start}-${end}`,
      quote: normalized,
      startOffset: start,
      endOffset: end,
      evidenceTerms: evidenceTermsFor(normalized),
    });
  };

  const htmlTableRegex = /<table[\s\S]*?<\/table>/gi;
  for (const match of text.matchAll(htmlTableRegex)) {
    addTable(match[0], match.index ?? 0, (match.index ?? 0) + match[0].length, 'HTML table 独立证据块');
  }

  const lines = text.split('\n');
  let offset = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] || '';
    const nextLine = lines[i + 1] || '';
    const isHeader = line.includes('|') && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(nextLine);
    if (!isHeader) {
      offset += line.length + 1;
      continue;
    }
    const startLine = i;
    let endLine = i + 2;
    while (endLine < lines.length && (lines[endLine] || '').includes('|') && (lines[endLine] || '').trim()) {
      endLine += 1;
    }
    const tableText = lines.slice(startLine, endLine).join('\n');
    const start = offset;
    const end = start + tableText.length;
    addTable(tableText, start, end, 'Markdown table 独立证据块');
    for (let j = i; j < endLine; j += 1) offset += (lines[j] || '').length + 1;
    i = endLine - 1;
  }

  return chunks;
}

function createFullTextChunks(text, chunkSize = 3200, overlap = 420) {
  const tableChunks = createTableEvidenceChunks(text);
  const chunks = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(text.length, start + chunkSize);
    if (end < text.length) {
      const paragraphBreak = text.lastIndexOf('\n\n', end);
      if (paragraphBreak > start + Math.floor(chunkSize * 0.45)) end = paragraphBreak;
    }
    const quote = text.slice(start, end).trim();
    if (!quote) {
      start = end + 1;
      continue;
    }
    const id = `chunk-${chunks.length + 1}`;
    chunks.push({
      id,
      title: `全文 Chunk ${chunks.length + 1}`,
      reason: `PDF/Markdown 全文切片，字符 ${start}-${end}`,
      quote,
      startOffset: start,
      endOffset: end,
    });
    if (end >= text.length) break;
    start = Math.max(0, end - overlap);
  }
  return [...tableChunks, ...chunks];
}

function evidenceTermsFor(value) {
  return String(value || '')
    .split(/[;；,，。()\[\]\s]+/)
    .map((term) => term.trim())
    .filter((term) => term.length >= 5)
    .slice(0, 8);
}

function findBestChunkId(chunks, needles) {
  return findBestChunkIds(chunks, needles, 1)[0] || chunks[0]?.id || 'chunk-1';
}

function findBestChunkIds(chunks, needles, limit = 3) {
  const normalizedNeedles = needles.map((needle) => compactText(needle || '')).filter((needle) => needle.length >= 12);
  if (normalizedNeedles.length === 0) return chunks[0]?.id ? [chunks[0].id] : [];
  const normalizedChunks = chunks.map((chunk) => ({ id: chunk.id, text: compactText(chunk.quote) }));
  for (const needle of normalizedNeedles) {
    const exact = normalizedChunks.filter((chunk) => chunk.text.includes(needle.slice(0, Math.min(needle.length, 260))));
    if (exact.length > 0) return exact.slice(0, limit).map((chunk) => chunk.id);
  }
  const tokens = normalizedNeedles
    .join(' ')
    .split(/[^\p{L}\p{N}._:>+-]+/u)
    .filter((token) => token.length >= 4)
    .slice(0, 80);
  return normalizedChunks
    .map((chunk) => ({
      id: chunk.id,
      score: tokens.reduce((total, token) => total + (chunk.text.includes(token) ? 1 : 0), 0),
    }))
    .sort((a, b) => b.score - a.score)
    .filter((chunk) => chunk.score > 0)
    .slice(0, limit)
    .map((chunk) => chunk.id);
}

function attachFullTextChunks(parsedResult, text) {
  const fullChunks = createFullTextChunks(text);
  if (fullChunks.length === 0) return parsedResult;
  const sourceMap = new Map();
  for (const chunk of parsedResult.chunks) {
    sourceMap.set(chunk.id, findBestChunkId(fullChunks, [chunk.quote, chunk.reason, chunk.title]));
  }
  const pm3Rows = parsedResult.pm3Rows.map((row) => {
    const fieldSources = {};
    const fieldHighlights = {};
    for (const [field, value] of Object.entries(row)) {
      if (field === 'source') continue;
      const terms = evidenceTermsFor(value);
      const chunkIds = [...new Set(findBestChunkIds(fullChunks, [value, row.sourceIndex, row.rawTableRow], 3))].filter(Boolean);
      fieldSources[field] = chunkIds;
      fieldHighlights[field] = terms;
    }
    const evidenceSource = findBestChunkId(fullChunks, [row.rawTableRow, row.sourceIndex, row.summary, row.transVariant, row.title]);
    const source = evidenceSource.startsWith('table-') ? evidenceSource : sourceMap.get(row.source) || evidenceSource;
    return { ...row, source, fieldSources, fieldHighlights };
  });
  const candidates = parsedResult.candidates.map((candidate) => {
    const source = sourceMap.get(candidate.source) || findBestChunkId(fullChunks, [candidate.variant, candidate.partner, candidate.context]);
    return { ...candidate, source };
  });
  return {
    ...parsedResult,
    candidates,
    pm3Rows,
    chunks: fullChunks,
    documentMarkdown: text,
  };
}

function buildPm3ExtractionPrompt({ fileName, text }) {
  return `你是遗传病 PM3 证据提取专家。请只基于提供的论文文本，抽取 PM3 汇总表结构化信息。

必须严格返回 JSON，不要 markdown fence，不要额外解释。

输出 JSON schema:
{
  "candidates": [
    {
      "variant": "候选 DNA/HGVS/论文位点表示；没有则 not stated",
      "protein": "蛋白变化；没有则 not stated",
      "gene": "基因；没有则 not stated",
      "patients": "关联患者数/病例描述；没有则 not stated",
      "context": "关联合子状态/上下文",
      "partner": "第二等位基因/trans/cis partner；没有则 not stated",
      "source": "chunk-1"
    }
  ],
  "pm3Rows": [
    {
      "pmid": "PMID；没有则 not stated",
      "title": "标题；没有则 not stated",
      "authors": "作者；没有则 not stated",
      "patientCount": "患者数",
      "patientAge": "患者年龄",
      "clinicalDisease": "患者临床疾病",
      "clinicalPhenotype": "患者临床表型",
      "familyInfo": "家系情况",
      "pathogenicity": "致病性（作者结论是否致病/疑似致病/不致病可能有其它位点）",
      "zygosity": "关联合子状态",
      "transVariant": "反式(trans)位点",
      "cisVariant": "顺式(cis)位点",
      "sourceIndex": "来源索引（表编号+行号/段落/页码等可回溯位置）",
      "rawTableRow": "表格原始行内容，保留原文",
      "literatureBackground": "文献背景(是什么研究，最终什么结论)",
      "summary": "总结：该变异已在[至少]XX名患有[疾病/表型]的个体中被检测到...",
      "extractionProcess": "AI提取过程：说明如何定位和判断",
      "source": "chunk-1"
    }
  ],
  "chunks": [
    {
      "id": "chunk-1",
      "title": "来源标题",
      "reason": "为什么作为证据",
      "quote": "可回溯的原文短摘录"
    }
  ],
  "selectedVariant": "最适合作为默认 PM3 目标位点的 HGVS/论文表示"
}

规则:
- 字段必须完整，缺失写 "not stated" 或 "未明确提及"。
- pm3Rows 必须按患者/病例/家系维度拆行：一个患者、一个 Case、一个家系或一个可独立计数的 PM3 证据单元对应一行。
- 不要把 Case 1/Case 2/Case 3 或多个患者合并到同一条 pm3Rows 的 patientAge、transVariant、rawTableRow、summary 中；文中有 3 个病例就输出 3 行。
- PMID、title、authors、literatureBackground 是文献维度字段，可以在每个患者行中重复填写同一篇文章的信息，但不要因为同一篇 PMID 只输出一条合并行。
- 患者年龄、表型、家系、合子状态、trans/cis 位点、rawTableRow 等患者维度信息如果来自表格，必须优先引用表格；sourceIndex 必须写明表号/表名/行号/病例编号。
- 每条 pm3Rows.source 必须对应 chunks 中的 id；表格证据可以使用 table-1/table-2 这类来源 id。
- sourceIndex 必须尽可能指出表号、行号、补充表、段落或页码；不要只写“正文”。
- rawTableRow 必须保留原始证据文本，便于人工复核。
- 不要编造 PMID、病例、trans/cis 或致病性结论。

文件名: ${fileName}

论文文本:
${truncateForModel(text)}
`;
}

function extractJsonObject(content) {
  const trimmed = content.trim();
  if (trimmed.startsWith('{')) return trimmed;
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) return fenced[1].trim();
  const start = trimmed.indexOf('{');
  const end = trimmed.lastIndexOf('}');
  if (start >= 0 && end > start) return trimmed.slice(start, end + 1);
  return trimmed;
}

async function callOpenAiCompatible({ modelSettings, fileName, text }) {
  if (!modelSettings) {
    const err = new Error('Missing model settings: please set API URL, model name and API key');
    err.statusCode = 400;
    throw err;
  }
  const prompt = buildPm3ExtractionPrompt({ fileName, text });
  const response = await fetch(`${normalizeApiUrl(modelSettings.apiUrl)}/chat/completions`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${modelSettings.apiKey}`,
    },
    body: JSON.stringify({
      model: modelSettings.modelName,
      messages: [
        {
          role: 'system',
          content: 'You extract biomedical PM3 evidence and return strict JSON only.',
        },
        { role: 'user', content: prompt },
      ],
      temperature: 0,
      response_format: { type: 'json_object' },
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`LLM request failed (${response.status}): ${detail.slice(0, 1000)}`);
  }

  const payload = await response.json();
  const content = payload.choices?.[0]?.message?.content;
  if (!content) throw new Error('LLM response did not contain message content');
  const parsed = JSON.parse(extractJsonObject(content));
  return ParsedResultSchema.parse(parsed);
}

function buildServer() {
  const app = Fastify({ logger: true, bodyLimit: 80 * 1024 * 1024 });

  app.addHook('onRequest', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*');
    reply.header('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS');
    reply.header('Access-Control-Allow-Headers', 'Content-Type');
    if (request.method === 'OPTIONS') {
      return reply.status(204).send();
    }
  });

  app.get('/api/health', async () => ({ ok: true }));

  app.post('/api/pm3/documents', async (request, reply) => {
    requireStorageEnv();
    const body = UploadSchema.parse(request.body);
    const buffer = Buffer.from(body.data, 'base64');
    const actualHash = createHash('sha256').update(buffer).digest('hex');
    const hash = body.hash.toLowerCase();
    if (actualHash !== hash) {
      return reply.status(400).send({ success: false, error: 'file hash mismatch' });
    }

    const id = randomUUID();
    const safeFileName = body.fileName.replace(/[^\w.\-()[\]\u4e00-\u9fa5]+/g, '_');
    const s3Key = `autopm3/documents/${id}/${safeFileName}`;
    await s3Client.send(
      new PutObjectCommand({
        Bucket: env.S3_BUCKET,
        Key: s3Key,
        Body: buffer,
        ContentType: body.mimeType,
      }),
    );

    const rows = await sql`
      insert into autopm3_documents
        (id, file_name, mime_type, file_hash, s3_key, status, parsed_result, error_message)
      values
        (${id}, ${body.fileName}, ${body.mimeType}, ${hash}, ${s3Key}, 'queued', '{}'::jsonb, null)
      returning *
    `;

    enqueueParseTask({
      id,
      fileName: body.fileName,
      mimeType: body.mimeType,
      s3Key,
      modelSettings: body.modelSettings,
      parsedResult: body.parsedResult,
    });

    return reply.status(202).send({ success: true, data: rowToDocument(rows[0]) });
  });

  app.get('/api/pm3/documents', async () => {
    requireStorageEnv();
    const rows = await sql`
      select id, file_name, mime_type, file_hash, s3_key, status, parsed_result, created_at, updated_at
      from autopm3_documents
      order by created_at desc
      limit 100
    `;
    return { success: true, data: rows.map(rowToDocument) };
  });

  app.get('/api/pm3/documents/:id', async (request, reply) => {
    requireStorageEnv();
    const { id } = request.params;
    const rows = await sql`select * from autopm3_documents where id = ${id} limit 1`;
    if (rows.length === 0) return reply.status(404).send({ success: false, error: 'document not found' });
    return { success: true, data: rowToDocument(rows[0]) };
  });

  app.get('/api/pm3/documents/:id/download', async (request, reply) => {
    requireStorageEnv();
    const { id } = request.params;
    const rows = await sql`select s3_key from autopm3_documents where id = ${id} limit 1`;
    if (rows.length === 0) return reply.status(404).send({ success: false, error: 'document not found' });
    const url = await getSignedUrl(
      s3Client,
      new GetObjectCommand({ Bucket: env.S3_BUCKET, Key: rows[0].s3_key }),
      { expiresIn: 3600 },
    );
    return { success: true, data: { url } };
  });

  app.delete('/api/pm3/documents/:id', async (request, reply) => {
    requireStorageEnv();
    const { id } = request.params;
    const rows = await sql`select * from autopm3_documents where id = ${id} limit 1`;
    if (rows.length === 0) return reply.status(404).send({ success: false, error: 'document not found' });
    await s3Client.send(new DeleteObjectCommand({ Bucket: env.S3_BUCKET, Key: rows[0].s3_key }));
    await sql`delete from autopm3_documents where id = ${id}`;
    return { success: true, data: rowToDocument(rows[0]) };
  });

  app.setErrorHandler((err, _request, reply) => {
    const status = err.statusCode || 500;
    reply.status(status).send({ success: false, error: err.message || 'internal error' });
  });

  return app;
}

await migrate();
const app = buildServer();
await app.listen({ host: env.HOST, port: env.PORT });
