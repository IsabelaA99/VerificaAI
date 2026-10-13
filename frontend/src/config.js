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
 * }} AppConfig
 */

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
  })
}

export const config = createConfig()
