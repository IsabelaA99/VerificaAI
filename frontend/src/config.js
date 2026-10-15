// @ts-check
// Configuração da interface, lida das variáveis VITE_* (veja .env.example).
//
// RNF16: tudo aqui vai para o pacote enviado ao navegador. Nunca coloque segredo.

import { RESPONSE_DEADLINE_MS } from './domain/limits.js'

/** @typedef {'demo' | 'off'} FeatureMode */

/**
 * @typedef {{
 *   apiBaseUrl: string,
 *   requestTimeoutMs: number,
 *   urlInput: boolean,
 *   accountsMode: FeatureMode,
 *   feedbackMode: FeatureMode,
 *   backend: { urlAnalysis: boolean, sources: boolean },
 *   whatsapp: { number: string, joinCode: string },
 * }} AppConfig
 */

// Chatbot no sandbox da Twilio: o número é o do sandbox (o mesmo para todas as contas) e o código
// "join …" é o da conta que roda o chatbot. Com um número oficial, o código fica vazio.
const WHATSAPP_SANDBOX_NUMBER = '14155238886'
const WHATSAPP_SANDBOX_JOIN_CODE = 'join division-facing'

/** Só os dígitos, no formato que o wa.me espera (código do país, sem "+"). @param {string | undefined} value */
const toPhoneDigits = (value) => (value ?? '').replace(/\D/g, '')

/** @param {string | undefined} value @param {boolean} fallback */
const toBool = (value, fallback) => (value === undefined || value === '' ? fallback : value === 'true')

/** @param {string | undefined} value @param {number} fallback */
const toPositiveNumber = (value, fallback) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

/** @param {string | undefined} value @returns {FeatureMode} */
const toMode = (value) => (value === 'off' ? 'off' : 'demo')

/**
 * @param {Record<string, string | undefined>} [env]
 * @returns {AppConfig}
 */
export function createConfig(env = import.meta.env) {
  return Object.freeze({
    apiBaseUrl: (env.VITE_API_BASE_URL || '/api').replace(/\/+$/, ''),
    requestTimeoutMs: toPositiveNumber(env.VITE_REQUEST_TIMEOUT_MS, RESPONSE_DEADLINE_MS),
    urlInput: toBool(env.VITE_FEATURE_URL_INPUT, true),
    accountsMode: toMode(env.VITE_ACCOUNTS_MODE),
    feedbackMode: toMode(env.VITE_FEEDBACK_MODE),
    // A API v1 já analisa links e consulta fontes. Estas opções só ajustam os textos
    // explicativos para uma implantação cujo back end ainda não ofereça esses recursos.
    backend: {
      urlAnalysis: toBool(env.VITE_BACKEND_URL_ANALYSIS, true),
      sources: toBool(env.VITE_BACKEND_SOURCES, true),
    },
    whatsapp: Object.freeze({
      number: toPhoneDigits(env.VITE_WHATSAPP_NUMBER) || WHATSAPP_SANDBOX_NUMBER,
      // Ausente: o código do sandbox. Vazio: número oficial, sem "join" (o link abre direto a conversa).
      joinCode: (env.VITE_WHATSAPP_JOIN_CODE ?? WHATSAPP_SANDBOX_JOIN_CODE).trim(),
    }),
  })
}

export const config = createConfig()
