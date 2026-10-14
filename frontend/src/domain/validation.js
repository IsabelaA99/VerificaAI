// @ts-check
// Validação da entrada no navegador (RF01, RF24). É uma conveniência: o servidor valida de novo
// e continua sendo a autoridade. Aqui o objetivo é dar o aviso certo, ao lado do campo, antes
// de gastar uma requisição (Nielsen: prevenção de erros; Wroblewski: validar no envio).

import { TEXT_LIMITS, URL_MAX_LENGTH } from './limits.js'
import { countCharacters, normalizeText } from './text.js'

/**
 * @typedef {{
 *   ok: false,
 *   scenario: 'text_insufficient' | 'text_too_long' | 'invalid_url' | 'url_in_text',
 *   code: string,
 *   field: 'text' | 'url',
 *   details: Record<string, unknown>,
 * }} ValidationFailure
 */
/** @typedef {{ ok: true, value: string, length: number }} ValidationSuccess */
/** @typedef {'text' | 'url'} InputType */

/**
 * Texto de 50 a 20.000 caracteres, contados depois da normalização (RF01). Nunca corta.
 * @param {string} raw
 * @returns {ValidationSuccess | ValidationFailure}
 */
export function validateText(raw) {
  const value = normalizeText(raw)
  const length = countCharacters(value)
  if (/^(?:https?:\/\/|www\.)\S+$/i.test(value)) {
    return { ok: false, scenario: 'url_in_text', code: 'url_in_text', field: 'text', details: {} }
  }
  if (length === 0) {
    return {
      ok: false,
      scenario: 'text_insufficient',
      code: 'empty_input',
      field: 'text',
      details: { length, min_chars: TEXT_LIMITS.min },
    }
  }
  if (length < TEXT_LIMITS.min) {
    return {
      ok: false,
      scenario: 'text_insufficient',
      code: 'text_too_short',
      field: 'text',
      details: { length, min_chars: TEXT_LIMITS.min },
    }
  }
  if (length > TEXT_LIMITS.max) {
    return {
      ok: false,
      scenario: 'text_too_long',
      code: 'text_too_long',
      field: 'text',
      details: { length, max_chars: TEXT_LIMITS.max },
    }
  }
  return { ok: true, value, length }
}

/**
 * Endereço público por HTTP ou HTTPS (RF01).
 * @param {string} raw
 * @returns {ValidationSuccess | ValidationFailure}
 */
export function validateUrl(raw) {
  const value = String(raw ?? '').trim()
  /** @param {string} reason @returns {ValidationFailure} */
  const fail = (reason) => ({
    ok: false,
    scenario: 'invalid_url',
    code: 'invalid_url',
    field: 'url',
    details: { reason },
  })

  if (!value) return fail('empty')
  if (value.length > URL_MAX_LENGTH) return fail('too_long')
  if (/\s/.test(value)) return fail('malformed')

  /** @type {URL} */
  let parsed
  try {
    parsed = new URL(value)
  } catch {
    return fail(/^[a-z][a-z0-9+.-]*:/i.test(value) ? 'scheme' : 'no_scheme')
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return fail('scheme')
  if (!parsed.hostname) return fail('malformed')
  return { ok: true, value, length: value.length }
}

/**
 * Valida só a opção escolhida (RF24: apenas a opção selecionada vai na solicitação).
 * @param {{ inputType: InputType, text?: string, url?: string }} input
 */
export function validateInput({ inputType, text = '', url = '' }) {
  return inputType === 'url' ? validateUrl(url) : validateText(text)
}
