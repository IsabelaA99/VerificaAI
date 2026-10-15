// @ts-check
// Tratamento de erros da interface (RF27).
//
// O RF27 pede que a interface diferencie sete cenários e ofereça uma ação possível em cada um:
//   1. URL inválida                  → invalid_url
//   2. página inacessível            → page_unreachable
//   3. texto insuficiente            → text_insufficient
//   4. idioma não suportado          → unsupported_language
//   5. indisponibilidade da API      → api_unavailable
//   6. falha na consulta de evidências → evidence_failure
//   7. tempo limite excedido         → timeout
//
// Além deles, a API real devolve outros estados que precisam de tratamento (texto longo demais,
// texto ilegível, entrada por link ainda indisponível, limite de requisições, análise não
// encontrada). Eles ficam em "OTHER_SCENARIOS" e não substituem os sete.
//
// A interface decide pelo CÓDIGO estável do erro (a API documenta o código como "estável para a
// interface"); mensagens e ações da API só são usadas quando o código é desconhecido.

import { TEXT_LIMITS, URL_MAX_LENGTH } from './limits.js'

/** @typedef {'invalid_url'|'page_unreachable'|'text_insufficient'|'unsupported_language'|'api_unavailable'|'evidence_failure'|'timeout'} Rf27Scenario */
/** @typedef {'text_too_long'|'text_unreadable'|'url_in_text'|'url_unavailable'|'rate_limited'|'incompatible_api'|'not_found'|'rejected'|'unknown'} OtherScenario */
/** @typedef {Rf27Scenario | OtherScenario} Scenario */
/** @typedef {'fix_input'|'paste_text'|'retry'|'reload'|'new_analysis'|'open_history'} ErrorActionId */

/** Os sete cenários exigidos pelo RF27, em ordem. */
export const RF27_SCENARIOS = /** @type {const} */ ([
  'invalid_url',
  'page_unreachable',
  'text_insufficient',
  'unsupported_language',
  'api_unavailable',
  'evidence_failure',
  'timeout',
])

export const OTHER_SCENARIOS = /** @type {const} */ ([
  'text_too_long',
  'text_unreadable',
  'url_in_text',
  'url_unavailable',
  'rate_limited',
  'incompatible_api',
  'not_found',
  'rejected',
  'unknown',
])

/** Rótulos dos botões de ação, usados por qualquer tela que mostre um erro. */
export const ACTION_LABELS = Object.freeze({
  fix_input: 'Corrigir o conteúdo',
  paste_text: 'Colar o texto da notícia',
  retry: 'Tentar de novo',
  reload: 'Recarregar a página',
  new_analysis: 'Iniciar nova análise',
  open_history: 'Abrir o histórico',
})

/**
 * Código de erro da API → cenário da interface.
 * Inclui os códigos emitidos pelo scraper do back end.
 */
const CODE_TO_SCENARIO = Object.freeze({
  // Existentes no back end hoje.
  empty_input: 'text_insufficient',
  text_too_short: 'text_insufficient',
  text_too_long: 'text_too_long',
  unreadable_input: 'text_unreadable',
  url_in_text: 'url_in_text',
  unsupported_language: 'unsupported_language',
  url_input_unavailable: 'url_unavailable',
  analysis_unavailable: 'api_unavailable',
  analysis_not_found: 'not_found',
  throttled: 'rate_limited',
  invalid_url: 'invalid_url',
  invalid_url_scheme: 'invalid_url',
  forbidden_url: 'invalid_url',
  dns_resolution_failed: 'page_unreachable',
  too_many_redirects: 'page_unreachable',
  url_timeout: 'page_unreachable',
  paywall_or_forbidden: 'page_unreachable',
  http_error: 'page_unreachable',
  non_text_content: 'page_unreachable',
  empty_scraped_text: 'page_unreachable',
})

/**
 * Nomes alternativos mantidos por compatibilidade com o contrato proposto pela interface.
 * Os códigos atuais do scraper estão no mapa principal acima.
 */
export const PROPOSED_CODE_TO_SCENARIO = Object.freeze({
  page_unreachable: 'page_unreachable',
  page_blocked: 'page_unreachable',
  page_paywalled: 'page_unreachable',
  page_not_text: 'page_unreachable',
  evidence_unavailable: 'evidence_failure',
})

/**
 * Erro da aplicação, já classificado em um cenário.
 */
export class AppError extends Error {
  /**
   * @param {{
   *   scenario: Scenario,
   *   code?: string,
   *   status?: number,
   *   field?: string | null,
   *   details?: Record<string, unknown>,
   *   retryAfterSeconds?: number | null,
   *   apiMessage?: string,
   *   apiAction?: string,
   * }} init
   */
  constructor(init) {
    super(init.apiMessage || init.scenario)
    this.name = 'AppError'
    /** @type {Scenario} */
    this.scenario = init.scenario
    this.code = init.code ?? init.scenario
    this.status = init.status ?? 0
    /** @type {string | null} */
    this.field = init.field ?? null
    /** @type {Record<string, unknown>} */
    this.details = init.details ?? {}
    /** @type {number | null} */
    this.retryAfterSeconds = init.retryAfterSeconds ?? null
    /** @type {string} */
    this.apiMessage = init.apiMessage ?? ''
    /** @type {string} */
    this.apiAction = init.apiAction ?? ''
  }
}

const numberFormat = new Intl.NumberFormat('pt-BR')
/** @param {unknown} value */
const formatCount = (value) => (typeof value === 'number' ? numberFormat.format(value) : '')

/**
 * @typedef {{ title: string, message: string, actions: ErrorActionId[], field: 'text' | 'url' | null }} ErrorView
 */

/** @type {Record<string, Omit<ErrorView, 'field'>>} */
const URL_PAGE_ERRORS = {
  dns_resolution_failed: {
    title: 'Não encontramos esse site.',
    message: 'Confira se o endereço foi digitado corretamente. Você também pode colar o texto da notícia.',
    actions: ['fix_input', 'paste_text'],
  },
  too_many_redirects: {
    title: 'O link redirecionou muitas vezes.',
    message: 'Use o endereço direto da matéria ou cole o texto da notícia.',
    actions: ['fix_input', 'paste_text'],
  },
  url_timeout: {
    title: 'O site demorou para responder.',
    message: 'Não conseguimos abrir a página no prazo disponível. Tente de novo ou cole o texto da notícia.',
    actions: ['retry', 'paste_text'],
  },
  network_error: {
    title: 'Não conseguimos conectar ao site da notícia.',
    message: 'Tente de novo em instantes ou cole o texto da notícia para continuar.',
    actions: ['retry', 'paste_text'],
  },
  paywall_or_forbidden: {
    title: 'O site bloqueou a leitura automática.',
    message: 'A página pode exigir assinatura ou restringir acessos automáticos. Se você tem acesso à notícia, copie e cole o texto.',
    actions: ['paste_text'],
  },
  http_error: {
    title: 'Não conseguimos abrir essa página.',
    message: 'O site retornou um erro. Confira se a matéria ainda está disponível, tente de novo ou cole o texto.',
    actions: ['paste_text', 'retry', 'fix_input'],
  },
  non_text_content: {
    title: 'Esse link não aponta para uma página de texto.',
    message: 'Use o link direto de uma matéria ou cole o texto da notícia.',
    actions: ['fix_input', 'paste_text'],
  },
  empty_scraped_text: {
    title: 'Não conseguimos extrair o texto dessa página.',
    message: 'Copie o conteúdo da notícia e cole na aba Colar texto para continuar.',
    actions: ['paste_text'],
  },
}

/**
 * Textos e ações de cada cenário. Linguagem simples, uma frase de problema e uma de saída.
 * @param {AppError} error
 * @returns {ErrorView}
 */
export function describeError(error) {
  const d = error.details
  switch (error.scenario) {
    case 'url_in_text':
      return {
        title: 'Você colou um link no campo de texto.',
        message: 'Use a aba Inserir link, se disponível, ou cole o conteúdo da notícia em Colar texto. O endereço sozinho não permite analisar a notícia.',
        actions: ['fix_input'],
        field: 'text',
      }
    case 'invalid_url': {
      if (error.code === 'forbidden_url') {
        return {
          title: 'Esse endereço é de uma rede interna ou restrita.',
          message: 'Use o endereço de uma notícia em um site público ou cole o texto da notícia.',
          actions: ['fix_input', 'paste_text'],
          field: 'url',
        }
      }
      const reason = d.reason
      const message =
        reason === 'empty'
          ? 'Cole o endereço completo da notícia, começando com http:// ou https://.'
          : reason === 'too_long'
            ? `O endereço passou de ${formatCount(URL_MAX_LENGTH)} caracteres. Use o endereço direto da notícia.`
            : reason === 'no_scheme'
              ? 'Falta o começo do endereço. Use o endereço completo, com http:// ou https:// antes do nome do site.'
              : 'Use o endereço completo da notícia, começando com http:// ou https://.'
      return {
        title: reason === 'empty' ? 'Falta o endereço da notícia.' : 'Esse endereço não parece válido.',
        message,
        actions: ['fix_input'],
        field: 'url',
      }
    }
    case 'page_unreachable':
      if (Object.hasOwn(URL_PAGE_ERRORS, error.code)) {
        return {
          ...URL_PAGE_ERRORS[error.code],
          message: `${URL_PAGE_ERRORS[error.code].message} Nenhuma análise foi feita só com o endereço.`,
          field: 'url',
        }
      }
      return {
        title: 'Não conseguimos abrir essa página.',
        message:
          'Ela pode estar fora do ar, pedir assinatura, bloquear acessos automáticos ou não ter texto. ' +
          'Nenhuma análise foi feita só com o endereço. Você pode colar o texto da notícia.',
        actions: ['paste_text', 'retry'],
        field: 'url',
      }
    case 'text_insufficient': {
      const min = typeof d.min_chars === 'number' ? d.min_chars : TEXT_LIMITS.min
      const length = formatCount(d.length)
      const has = length ? `Seu texto tem ${length} caracteres. ` : ''
      return {
        title: 'Precisamos de um pouco mais de texto.',
        message: `${has}Para analisar, o conteúdo precisa ter pelo menos ${formatCount(min)} caracteres. Cole o parágrafo completo ou a mensagem inteira.`,
        actions: ['fix_input'],
        field: 'text',
      }
    }
    case 'text_too_long': {
      const max = typeof d.max_chars === 'number' ? d.max_chars : TEXT_LIMITS.max
      const length = formatCount(d.length)
      const has = length ? `Seu texto tem ${length} caracteres e o limite é ${formatCount(max)}. ` : `O limite é de ${formatCount(max)} caracteres. `
      return {
        title: 'O texto passou do limite.',
        message: `${has}Nada foi cortado: envie só o trecho com a alegação principal.`,
        actions: ['fix_input'],
        field: 'text',
      }
    }
    case 'text_unreadable':
      return {
        title: 'Não conseguimos ler esse texto.',
        message: 'O conteúdo parece corrompido ou sem texto suficiente. Confira se ele foi colado corretamente.',
        actions: ['fix_input'],
        field: 'text',
      }
    case 'unsupported_language':
      return {
        title: 'O Apura só analisa textos em português.',
        message: 'O conteúdo enviado não parece estar em português. Envie um texto em português.',
        actions: ['fix_input'],
        field: 'text',
      }
    case 'url_unavailable':
      return {
        title: 'A análise por link ainda não está disponível.',
        message: 'Por enquanto, cole o texto da notícia para continuar.',
        actions: ['paste_text'],
        field: 'url',
      }
    case 'api_unavailable':
      return {
        title: 'O serviço de análise está indisponível.',
        message: error.details.offline
          ? 'Não foi possível conectar ao serviço. Confira sua conexão com a internet e tente de novo.'
          : 'Não foi possível concluir a análise agora. O problema não está no seu texto. Tente de novo em instantes.',
        actions: ['retry'],
        field: null,
      }
    case 'evidence_failure':
      return {
        title: d.partial === true ? 'A consulta às fontes foi parcial.' : 'Não foi possível consultar todas as fontes.',
        message: d.partial === true
          ? 'As fontes abaixo foram encontradas, mas outra consulta falhou. A lista pode estar incompleta. Para tentar novamente, inicie uma nova análise.'
          : 'Uma ou mais consultas falharam e nenhuma fonte foi encontrada nas consultas concluídas. O resultado pode estar incompleto. Para tentar novamente, inicie uma nova análise.',
        actions: ['new_analysis'],
        field: null,
      }
    case 'timeout':
      return {
        title: 'A análise demorou mais do que o esperado.',
        message: 'O limite é de 30 segundos e a resposta não chegou a tempo. Tente de novo.',
        actions: ['retry'],
        field: null,
      }
    case 'rate_limited': {
      const seconds = error.retryAfterSeconds
      return {
        title: 'Muitas solicitações em pouco tempo.',
        message: seconds
          ? `Aguarde cerca de ${seconds} ${seconds === 1 ? 'segundo' : 'segundos'} e tente de novo.`
          : 'Aguarde um instante e tente de novo.',
        actions: ['retry'],
        field: null,
      }
    }
    case 'incompatible_api':
      return {
        title: 'Esta página está desatualizada.',
        message: 'A versão do serviço mudou. Recarregue a página para continuar.',
        actions: ['reload'],
        field: null,
      }
    case 'not_found':
      return {
        title: 'Análise não encontrada.',
        message: 'O endereço pode estar incorreto ou essa análise não está mais disponível.',
        actions: ['new_analysis', 'open_history'],
        field: null,
      }
    case 'rejected':
      // Erro 4xx com código desconhecido: a API manda mensagem e ação em português.
      return {
        title: 'Não foi possível enviar esse conteúdo.',
        message: [error.apiMessage, error.apiAction].filter(Boolean).join(' ') || 'Confira o conteúdo e tente de novo.',
        actions: ['fix_input'],
        field: error.field === 'url' ? 'url' : error.field === 'text' ? 'text' : null,
      }
    default:
      return {
        title: 'Algo não saiu como esperado.',
        message: 'Não foi possível concluir agora. Tente de novo em instantes.',
        actions: ['retry'],
        field: null,
      }
  }
}

/**
 * Classifica uma resposta de erro HTTP da API.
 * @param {{ status: number, body: unknown, retryAfterSeconds?: number | null }} failure
 * @returns {AppError}
 */
export function classifyApiFailure({ status, body, retryAfterSeconds = null }) {
  const envelope = body && typeof body === 'object' && 'error' in body ? /** @type {any} */ (body).error : null
  const code = envelope && typeof envelope.code === 'string' ? envelope.code : ''
  const field = envelope && typeof envelope.field === 'string' ? envelope.field : null
  const base = {
    code: code || undefined,
    status,
    field,
    details: envelope && typeof envelope.details === 'object' && envelope.details ? { ...envelope.details } : {},
    retryAfterSeconds,
    apiMessage: envelope && typeof envelope.message === 'string' ? envelope.message : '',
    apiAction: envelope && typeof envelope.action === 'string' ? envelope.action : '',
  }

  // A falha ao buscar a notícia é diferente da perda de conexão navegador → API.
  if (code === 'network_error' && field === 'url') {
    return new AppError({ ...base, scenario: 'page_unreachable' })
  }
  const known = /** @type {Record<string, Scenario>} */ (CODE_TO_SCENARIO)[code] ?? /** @type {Record<string, Scenario>} */ (PROPOSED_CODE_TO_SCENARIO)[code]
  if (known) return new AppError({ ...base, scenario: known })

  // validation_error genérico (400 do serializer): decide pelo campo.
  if (code === 'validation_error') {
    if (field === 'url') return new AppError({ ...base, scenario: 'invalid_url' })
    if (field === 'text') return new AppError({ ...base, scenario: 'text_insufficient' })
    return new AppError({ ...base, scenario: 'rejected' })
  }

  // Sem código conhecido: decide pelo status HTTP.
  if (status === 429) return new AppError({ ...base, scenario: 'rate_limited' })
  if (status === 408 || status === 504) return new AppError({ ...base, scenario: 'timeout' })
  if (status === 404) return new AppError({ ...base, scenario: 'not_found' })
  if (status >= 500) return new AppError({ ...base, scenario: 'api_unavailable' })
  if (status >= 400) return new AppError({ ...base, scenario: 'rejected' })
  return new AppError({ ...base, scenario: 'unknown' })
}

/**
 * Falha de rede (sem resposta HTTP).
 * @param {{ offline?: boolean }} [options]
 */
export function networkFailure({ offline = false } = {}) {
  return new AppError({ scenario: 'api_unavailable', code: 'network_error', details: { offline } })
}

/** Tempo limite do RNF01 estourado no navegador. */
export function timeoutFailure() {
  return new AppError({ scenario: 'timeout', code: 'client_timeout' })
}

/** A API respondeu algo que esta versão da interface não sabe ler (RF29). */
export function incompatibleApiFailure(reason = '') {
  return new AppError({ scenario: 'incompatible_api', code: 'incompatible_api', details: { reason } })
}

/**
 * Erro de validação feito no navegador (antes do envio).
 * @param {import('./validation.js').ValidationFailure} failure
 */
export function fromValidation(failure) {
  return new AppError({
    scenario: failure.scenario,
    code: failure.code,
    field: failure.field,
    details: failure.details,
  })
}
