// @ts-check
// Modelo de uma análise na interface e leitura da resposta da API v1 (RF29).
//
// A API devolve JSON em snake_case; a interface trabalha com um objeto em camelCase, já
// validado. Se a resposta não bater com o contrato que esta versão da interface conhece, a
// leitura falha com o cenário "incompatible_api" em vez de mostrar um resultado errado.

import { incompatibleApiFailure } from './errors.js'
import { effectiveStatusCode, isStatusCode } from './status.js'

/** Versões da API que esta interface sabe ler (RF29: compatibilidade entre versões). */
export const SUPPORTED_API_VERSIONS = Object.freeze(['v1'])

/**
 * @typedef {import('./status.js').StatusCode} StatusCode
 * @typedef {'compatible' | 'conflicting' | 'contextual' | 'insufficient'} SourceRelation
 *
 * @typedef {{
 *   id: string,
 *   relation: SourceRelation,
 *   publisher: string | null,
 *   title: string | null,
 *   excerpt: string | null,
 *   publishedAt: string | null,
 *   url: string | null,
 *   reason: string | null,
 * }} Source
 *
 * @typedef {'disabled' | 'failed' | 'none' | 'found'} EvidenceStatus
 *
 * @typedef {{
 *   signal: number,
 *   capsRatio: number,
 *   exclamations: number,
 *   repeatedPunctuation: number,
 *   sensationalTerms: string[],
 *   components: { caps: number, punctuation: number, terms: number },
 * }} Indicators
 *
 * @typedef {{
 *   label: string | null,
 *   fakeProbability: number | null,
 *   confidence: number | null,
 *   calibrated: boolean,
 *   chunksAnalyzed: number | null,
 *   chunksTotal: number | null,
 *   fullyAnalyzed: boolean | null,
 *   aggregation: string | null,
 *   tokensAnalyzed: number | null,
 *   tokensTotal: number | null,
 *   discourseType: string | null,
 *   discourseLabel: string | null,
 *   isOutOfDomain: boolean,
 *   trainingScope: string | null,
 *   uncertaintyWarning: string | null,
 *   verdictTendency: string | null,
 *   semanticComparison: { consensus_status: string, consensus_summary: string } | null,
 *   lexicalAnalysis: { hedging_terms: string[] } | null,
 * }} ModelInfo
 *
 * @typedef {{
 *   value: number | null,
 *   signalsUsed: Record<string, number>,
 *   signalsMissing: string[],
 *   weights: Record<string, number>,
 *   formula: string,
 * }} RiskBreakdown
 *
 * @typedef {{
 *   model: string, modelSha256: string, rules: string, calibrator: string, schema: string, code: string,
 * }} Versions
 *
 * @typedef {{
 *   id: string,
 *   apiVersion: string,
 *   createdAt: string,
 *   inputType: 'text' | 'url',
 *   status: { code: StatusCode, label: string },
 *   riskIndex: number | null,
 *   claim: { summary: string, confirmedByUser: boolean },
 *   explanation: string[],
 *   abstention: { code: string, message: string }[],
 *   evidence: { status: EvidenceStatus, enabled: boolean, sources: Source[] },
 *   indicators: Indicators,
 *   model: ModelInfo,
 *   risk: RiskBreakdown,
 *   limitations: string[],
 *   recommendations: string[],
 *   versions: Versions,
 *   durationMs: number | null,
 *   expert: Record<string, unknown> | null,
 * }} Analysis
 */

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** @param {unknown} value @param {string} [fallback] */
const asString = (value, fallback = '') => (typeof value === 'string' ? value : fallback)

/** @param {unknown} value @returns {number | null} */
const asNumberOrNull = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** @param {unknown} value @returns {string[]} */
const asStringArray = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [])

/**
 * Aceita só endereços http(s). Qualquer outra coisa (javascript:, data:, relativo) vira null,
 * porque a URL vem de dados externos (RNF16: tratar conteúdo não confiável).
 * @param {unknown} value
 * @returns {string | null}
 */
export function safeHttpUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const url = new URL(value.trim())
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

/** Como cada relação entre fonte e alegação é escrita na tela e no resumo copiável (RF08, RF18). */
export const SOURCE_RELATION_LABELS = Object.freeze({
  compatible: 'Compatível com a alegação',
  conflicting: 'Conflitante com a alegação',
  contextual: 'Traz contexto',
  insufficient: 'Insuficiente para confirmar ou contestar',
})

/** Relações aceitas para uma fonte (RF08). Aceita os códigos em inglês e em português. */
/** @type {Readonly<Record<string, SourceRelation>>} */
const RELATION_ALIASES = Object.freeze({
  compatible: 'compatible',
  compativel: 'compatible',
  conflicting: 'conflicting',
  conflitante: 'conflicting',
  contextual: 'contextual',
  insufficient: 'insufficient',
  insuficiente: 'insufficient',
})

/**
 * PROPOSTA — o formato de uma fonte ainda não existe na API (Etapa 3; hoje "sources" é sempre
 * uma lista vazia). Campos assumidos: relation, publisher, title, excerpt, published_at, url,
 * relation_reason. Confirmar com o back end. Campos ausentes viram null ("não informado").
 * @param {unknown} raw
 * @param {number} index
 * @returns {Source | null}
 */
export function normalizeSource(raw, index) {
  if (!isRecord(raw)) return null
  const relation = RELATION_ALIASES[asString(raw.relation).toLowerCase()]
  // Sem relação demonstrável com a alegação, a fonte não altera nem aparece no resultado (RF08).
  if (!relation) return null
  return {
    id: asString(raw.id) || `source-${index}`,
    relation,
    publisher: asString(raw.publisher) || null,
    title: asString(raw.title) || null,
    excerpt: asString(raw.excerpt) || null,
    publishedAt: asString(raw.published_at) || null,
    url: safeHttpUrl(raw.url),
    reason: asString(raw.relation_reason) || null,
  }
}

/**
 * @param {unknown} raw
 * @returns {{ status: EvidenceStatus, enabled: boolean, sources: Source[] }}
 */
function normalizeEvidence(raw) {
  const evidence = isRecord(raw) ? raw : {}
  const enabled = evidence.enabled === true
  const sources = Array.isArray(evidence.sources)
    ? /** @type {Source[]} */ (evidence.sources.map(normalizeSource).filter(Boolean))
    : []
  // A API sinaliza falha total ou parcial com evidence.failed: true.
  // Mantemos a leitura de evidence.error para respostas de versões anteriores.
  const failed = evidence.failed === true || isRecord(evidence.error)
  /** @type {EvidenceStatus} */
  let status = 'disabled'
  if (enabled) status = failed ? 'failed' : sources.length ? 'found' : 'none'
  else if (failed) status = 'failed'
  return { status, enabled, sources }
}

/** @param {unknown} raw @returns {Indicators} */
function normalizeIndicators(raw) {
  const i = isRecord(raw) ? raw : {}
  const c = isRecord(i.components) ? i.components : {}
  return {
    signal: asNumberOrNull(i.signal) ?? 0,
    capsRatio: asNumberOrNull(i.caps_ratio) ?? 0,
    exclamations: asNumberOrNull(i.exclamations) ?? 0,
    repeatedPunctuation: asNumberOrNull(i.repeated_punctuation) ?? 0,
    sensationalTerms: asStringArray(i.sensational_terms),
    components: {
      caps: asNumberOrNull(c.caps) ?? 0,
      punctuation: asNumberOrNull(c.punctuation) ?? 0,
      terms: asNumberOrNull(c.terms) ?? 0,
    },
  }
}

/** @param {unknown} raw @returns {ModelInfo} */
function normalizeModel(raw) {
  const m = isRecord(raw) ? raw : {}
  const semantic = isRecord(m.semantic_comparison) ? m.semantic_comparison : null
  const lexical = isRecord(m.lexical_analysis) ? m.lexical_analysis : null
  return {
    label: asString(m.label) || null,
    fakeProbability: asNumberOrNull(m.fake_probability),
    confidence: asNumberOrNull(m.confidence),
    calibrated: m.calibrated === true,
    chunksAnalyzed: asNumberOrNull(m.chunks_analyzed),
    chunksTotal: asNumberOrNull(m.chunks_total),
    fullyAnalyzed: typeof m.fully_analyzed === 'boolean' ? m.fully_analyzed : null,
    aggregation: asString(m.aggregation) || null,
    tokensAnalyzed: asNumberOrNull(m.tokens_analyzed),
    tokensTotal: asNumberOrNull(m.tokens_total),
    discourseType: asString(m.discourse_type) || null,
    discourseLabel: asString(m.discourse_label) || null,
    isOutOfDomain: m.is_out_of_domain === true,
    trainingScope: asString(m.training_scope) || null,
    uncertaintyWarning: asString(m.uncertainty_warning) || null,
    verdictTendency: asString(m.verdict_tendency) || null,
    semanticComparison: semantic
      ? { consensus_status: asString(semantic.consensus_status), consensus_summary: asString(semantic.consensus_summary) }
      : null,
    lexicalAnalysis: lexical ? { hedging_terms: asStringArray(lexical.hedging_terms) } : null,
  }
}

/** @param {unknown} raw @returns {RiskBreakdown} */
function normalizeRisk(raw) {
  const r = isRecord(raw) ? raw : {}
  /** @type {Record<string, number>} */
  const signalsUsed = {}
  if (isRecord(r.signals_used)) {
    for (const [key, value] of Object.entries(r.signals_used)) {
      if (typeof value === 'number') signalsUsed[key] = value
    }
  }
  /** @type {Record<string, number>} */
  const weights = {}
  if (isRecord(r.weights)) {
    for (const [key, value] of Object.entries(r.weights)) {
      if (typeof value === 'number') weights[key] = value
    }
  }
  return {
    value: asNumberOrNull(r.value),
    signalsUsed,
    signalsMissing: asStringArray(r.signals_missing),
    weights,
    formula: asString(r.formula),
  }
}

/** @param {unknown} raw @returns {Versions} */
function normalizeVersions(raw) {
  const v = isRecord(raw) ? raw : {}
  return {
    model: asString(v.model),
    modelSha256: asString(v.model_sha256),
    rules: asString(v.rules),
    calibrator: asString(v.calibrator),
    schema: asString(v.schema),
    code: asString(v.code),
  }
}

/**
 * Lê e valida a resposta da API v1. Lança AppError (incompatible_api) se faltar algo essencial.
 * @param {unknown} raw corpo JSON de POST /api/v1/analyses/ ou GET /api/v1/analyses/{id}/
 * @returns {Analysis}
 */
export function normalizeAnalysis(raw) {
  if (!isRecord(raw)) throw incompatibleApiFailure('A resposta não é um objeto JSON.')

  const apiVersion = asString(raw.api_version)
  if (!SUPPORTED_API_VERSIONS.includes(apiVersion)) {
    throw incompatibleApiFailure(`Versão de API não suportada: ${apiVersion || 'ausente'}.`)
  }

  const id = asString(raw.id)
  if (!id) throw incompatibleApiFailure('A resposta não traz o identificador da análise.')

  const createdAt = asString(raw.created_at)
  if (!createdAt || Number.isNaN(Date.parse(createdAt))) {
    throw incompatibleApiFailure('A resposta não traz uma data válida.')
  }

  const status = isRecord(raw.status) ? raw.status : null
  if (!status || !isStatusCode(status.code)) {
    throw incompatibleApiFailure('A resposta traz um status desconhecido.')
  }

  const riskIndex = raw.risk_index === null || raw.risk_index === undefined ? null : asNumberOrNull(raw.risk_index)
  if (raw.risk_index !== null && raw.risk_index !== undefined && (riskIndex === null || riskIndex < 0 || riskIndex > 100)) {
    throw incompatibleApiFailure('O índice de risco está fora do intervalo de 0 a 100.')
  }

  const claim = isRecord(raw.claim) ? raw.claim : {}
  const inputType = raw.input_type === 'url' ? 'url' : 'text'

  /** @type {{ code: string, message: string }[]} */
  const abstention = Array.isArray(raw.abstention)
    ? raw.abstention
        .filter(isRecord)
        .map((item) => ({ code: asString(item.code), message: asString(item.message) }))
        .filter((item) => item.message)
    : []

  return {
    id,
    apiVersion,
    createdAt,
    inputType,
    status: { code: status.code, label: asString(status.label) },
    riskIndex,
    claim: { summary: asString(claim.summary), confirmedByUser: claim.confirmed_by_user === true },
    explanation: asStringArray(raw.explanation),
    abstention,
    evidence: normalizeEvidence(raw.evidence),
    indicators: normalizeIndicators(raw.indicators),
    model: normalizeModel(raw.model),
    risk: normalizeRisk(raw.risk),
    limitations: asStringArray(raw.limitations),
    recommendations: asStringArray(raw.recommendations),
    versions: normalizeVersions(raw.versions),
    durationMs: asNumberOrNull(raw.duration_ms),
    expert: isRecord(raw.expert) ? raw.expert : null,
  }
}

/**
 * Status que a interface exibe (RF16: inconclusivo tem prioridade).
 * @param {Analysis} analysis
 * @returns {StatusCode}
 */
export function statusOf(analysis) {
  return effectiveStatusCode(analysis)
}
