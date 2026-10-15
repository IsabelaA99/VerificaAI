import { describe, expect, it } from 'vitest'
import { apiErrors, makeApiError } from '../test/fixtures.js'
import {
  ACTION_LABELS,
  AppError,
  OTHER_SCENARIOS,
  PROPOSED_CODE_TO_SCENARIO,
  RF27_SCENARIOS,
  classifyApiFailure,
  describeError,
  fromValidation,
  incompatibleApiFailure,
  networkFailure,
  timeoutFailure,
} from './errors.js'
import { validateText, validateUrl } from './validation.js'

const allScenarios = [...RF27_SCENARIOS, ...OTHER_SCENARIOS]

describe('catálogo de erros (RF27)', () => {
  it('cobre os sete cenários exigidos pelo RF27', () => {
    expect(RF27_SCENARIOS).toEqual([
      'invalid_url',
      'page_unreachable',
      'text_insufficient',
      'unsupported_language',
      'api_unavailable',
      'evidence_failure',
      'timeout',
    ])
  })

  it.each(allScenarios)('o cenário %s tem título, mensagem e ao menos uma ação conhecida', (scenario) => {
    const view = describeError(new AppError({ scenario }))
    expect(view.title.trim()).not.toBe('')
    expect(view.message.trim()).not.toBe('')
    expect(view.actions.length).toBeGreaterThan(0)
    for (const action of view.actions) expect(ACTION_LABELS[action]).toBeTruthy()
  })

  it('cada cenário do RF27 oferece a ação prevista no critério de aceite', () => {
    const actions = (scenario) => describeError(new AppError({ scenario })).actions
    expect(actions('invalid_url')).toContain('fix_input') // corrigir a entrada
    expect(actions('page_unreachable')).toContain('paste_text') // colar o texto
    expect(actions('text_insufficient')).toContain('fix_input')
    expect(actions('unsupported_language')).toContain('fix_input')
    expect(actions('api_unavailable')).toContain('retry') // tentar novamente
    expect(actions('evidence_failure')).toContain('new_analysis')
    expect(actions('timeout')).toContain('retry')
  })

  it('a falha de página nunca promete análise a partir só do endereço (RF03)', () => {
    const { message } = describeError(new AppError({ scenario: 'page_unreachable' }))
    expect(message).toMatch(/Nenhuma análise foi feita só com o endereço/)
  })

  it('usa o nome Apura, nunca o nome antigo, mesmo quando a API ainda diz Fake Eyes', () => {
    const error = classifyApiFailure({ status: 400, body: apiErrors.unsupportedLanguage })
    const view = describeError(error)
    expect(view.message).not.toMatch(/Fake Eyes/)
    expect(view.title).toMatch(/Apura/)
  })
})

describe('classifyApiFailure com respostas reais do back end', () => {
  it.each([
    ['textTooShort', 400, 'text_insufficient'],
    ['emptyInput', 400, 'text_insufficient'],
    ['textTooLong', 400, 'text_too_long'],
    ['unreadable', 400, 'text_unreadable'],
    ['unsupportedLanguage', 400, 'unsupported_language'],
    ['urlUnavailable', 501, 'url_unavailable'],
    ['analysisUnavailable', 503, 'api_unavailable'],
    ['notFound', 404, 'not_found'],
    ['throttled', 429, 'rate_limited'],
    ['validationUrl', 400, 'invalid_url'],
  ])('%s (HTTP %s) → %s', (key, status, scenario) => {
    const error = classifyApiFailure({ status, body: apiErrors[key] })
    expect(error).toBeInstanceOf(AppError)
    expect(error.scenario).toBe(scenario)
    expect(error.status).toBe(status)
  })

  it('texto curto: mostra o tamanho enviado e o mínimo, vindos dos detalhes da API', () => {
    const view = describeError(classifyApiFailure({ status: 400, body: apiErrors.textTooShort }))
    expect(view.message).toMatch(/12 caracteres/)
    expect(view.message).toMatch(/pelo menos 50 caracteres/)
    expect(view.field).toBe('text')
  })

  it('texto longo: diz que nada foi cortado (RF01) e usa o separador de milhar do português', () => {
    const view = describeError(classifyApiFailure({ status: 400, body: apiErrors.textTooLong }))
    expect(view.message).toMatch(/5\.320 caracteres/)
    expect(view.message).toMatch(/limite é 5\.000/)
    expect(view.message).toMatch(/Nada foi cortado/)
  })

  it('limite de requisições: usa o Retry-After quando existe', () => {
    const error = classifyApiFailure({ status: 429, body: apiErrors.throttled, retryAfterSeconds: 12 })
    expect(describeError(error).message).toMatch(/12 segundos/)
    const sem = classifyApiFailure({ status: 429, body: apiErrors.throttled })
    expect(describeError(sem).message).toMatch(/Aguarde um instante/)
  })

  it('validation_error em campo desconhecido mostra a mensagem e a ação da própria API', () => {
    const body = makeApiError({
      code: 'validation_error',
      message: 'Valor inválido.',
      action: 'Corrija os dados enviados e tente novamente.',
      field: 'input_type',
    })
    const error = classifyApiFailure({ status: 400, body })
    expect(error.scenario).toBe('rejected')
    const view = describeError(error)
    expect(view.message).toContain('Valor inválido.')
    expect(view.message).toContain('Corrija os dados enviados')
  })

  it('sem corpo JSON (ex.: página 502 do nginx), decide pelo status HTTP', () => {
    expect(classifyApiFailure({ status: 502, body: null }).scenario).toBe('api_unavailable')
    expect(classifyApiFailure({ status: 503, body: '<html>' }).scenario).toBe('api_unavailable')
    expect(classifyApiFailure({ status: 504, body: null }).scenario).toBe('timeout')
    expect(classifyApiFailure({ status: 404, body: null }).scenario).toBe('not_found')
    expect(classifyApiFailure({ status: 418, body: null }).scenario).toBe('rejected')
  })

  it('códigos propostos para as Etapas 2 e 3 já são entendidos (RF27, cenários 1, 2 e 6)', () => {
    expect(PROPOSED_CODE_TO_SCENARIO.page_unreachable).toBe('page_unreachable')
    for (const code of ['invalid_url', 'page_unreachable', 'page_blocked', 'page_paywalled', 'page_not_text', 'evidence_unavailable']) {
      const error = classifyApiFailure({ status: 422, body: makeApiError({ code }) })
      expect(['invalid_url', 'page_unreachable', 'evidence_failure']).toContain(error.scenario)
    }
  })
})

describe('falhas feitas no navegador', () => {
  it('tempo limite do RNF01 vira o cenário timeout', () => {
    const error = timeoutFailure()
    expect(error.scenario).toBe('timeout')
    expect(describeError(error).message).toMatch(/30 segundos/)
  })

  it('falha de rede vira indisponibilidade e distingue "sem internet"', () => {
    expect(describeError(networkFailure()).message).toMatch(/não está no seu texto/)
    expect(describeError(networkFailure({ offline: true })).message).toMatch(/conexão com a internet/)
    expect(networkFailure().scenario).toBe('api_unavailable')
  })

  it('versão da API incompatível pede recarregar a página (RF29)', () => {
    const error = incompatibleApiFailure('v2')
    expect(error.scenario).toBe('incompatible_api')
    expect(describeError(error).actions).toEqual(['reload'])
  })

  it('validação do navegador usa os mesmos cenários e textos da API', () => {
    const short = describeError(fromValidation(/** @type {any} */ (validateText('curto'))))
    expect(short.message).toMatch(/pelo menos 50 caracteres/)
    const url = describeError(fromValidation(/** @type {any} */ (validateUrl('exemplo.com'))))
    expect(url.title).toMatch(/endereço/)
    expect(url.message).toMatch(/http:\/\/ ou https:\/\//)
    const empty = describeError(fromValidation(/** @type {any} */ (validateUrl(''))))
    expect(empty.title).toMatch(/Falta o endereço/)
  })
})
