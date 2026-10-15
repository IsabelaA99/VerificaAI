import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useParams } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'
import { formatNumber } from '../../domain/format.js'
import { TEXT_LIMITS, VISITOR_LIMIT } from '../../domain/limits.js'
import { createDemoAuthGateway } from '../../services/gateways.js'
import { apiErrors, makeApiAnalysis, makeApiError } from '../../test/fixtures.js'
import { createTestServices, jsonResponse, renderWithApp } from '../../test/render.jsx'
import AnalysisForm, { EXAMPLE_TEXT } from './AnalysisForm.jsx'

// RF24 (só a opção escolhida), RF25 (sem envio duplicado, estado de espera), RF27 (erros com ação),
// RF33 (limite de visitante) e RNF17 (confirmação imediata), na tela do formulário.

const VALID_TEXT = 'A prefeitura anunciou que o transporte coletivo terá novos horários a partir da próxima semana.'
const created = (body = makeApiAnalysis()) => jsonResponse(body, { status: 201 })

function ResultStub() {
  const { id } = useParams()
  return <p>RESULTADO {id}</p>
}

function setup({ fetchImpl = vi.fn(async () => created()), env, clock, auth } = {}) {
  const services = createTestServices({ fetchImpl, env, clock, auth })
  const utils = renderWithApp(
    <Routes>
      <Route path="/" element={<AnalysisForm />} />
      <Route path="/resultado/:id" element={<ResultStub />} />
      <Route path="/entrar" element={<p>PÁGINA ENTRAR</p>} />
      <Route path="/criar-conta" element={<p>PÁGINA CRIAR CONTA</p>} />
    </Routes>,
    { services },
  )
  return { services, fetchImpl, ...utils }
}

const textarea = () => screen.getByRole('textbox', { name: 'Texto da notícia ou mensagem' })
const submit = () => screen.getByRole('button', { name: /Verificar agora/ })
const bodyOf = (fetchImpl, call = 0) => JSON.parse(fetchImpl.mock.calls[call][1].body)

/**
 * O painel de erro do formulário. A região de avisos (toast) também tem role="alert": ela existe sempre,
 * vazia, para que o leitor de tela anuncie o que entrar nela. Por isso o painel é procurado dentro de
 * ".error-panel", e não só pelo papel.
 */
const queryErrorAlert = () => screen.queryAllByRole('alert').find((el) => el.closest('.error-panel')) ?? null
const findErrorAlert = () =>
  waitFor(() => {
    const alert = queryErrorAlert()
    expect(alert).not.toBeNull()
    return alert
  })

/** fetch que só responde quando o teste mandar, e respeita o cancelamento. */
function deferredFetch() {
  const resolvers = []
  const signals = []
  const fetchImpl = vi.fn(
    (_url, { signal }) =>
      new Promise((resolve, reject) => {
        resolvers.push(resolve)
        signals.push(signal)
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }),
  )
  return { fetchImpl, signals, respond: (response) => resolvers.shift()(response) }
}

describe('estrutura e acessibilidade', () => {
  it('mostra o campo de texto, o contador, as abas e o medidor do visitante', () => {
    setup()
    expect(screen.getByRole('heading', { name: 'O que vamos investigar?' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Colar texto', selected: true })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Inserir link' })).not.toHaveAttribute('aria-disabled')
    expect(textarea()).toHaveAccessibleDescription(new RegExp(`Entre 50 e ${formatNumber(TEXT_LIMITS.max)} caracteres`))
    expect(screen.getByText(`0 / ${formatNumber(TEXT_LIMITS.max)}`)).toBeInTheDocument()
    expect(screen.getByText(/3 de 3/)).toBeInTheDocument()
    expect(screen.getByText(/a janela de 24 h começa na primeira análise/)).toBeInTheDocument()
    expect(submit()).toBeInTheDocument()
  })

  it('não tem violações de acessibilidade (axe)', async () => {
    const { container } = setup()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('com o envio por link desligado, a aba mostra "Em breve" e explica, sem poder ser escolhida', async () => {
    setup({ env: { VITE_FEATURE_URL_INPUT: 'false' } })
    const tab = screen.getByRole('tab', { name: /Inserir link/ })
    expect(tab).toHaveAttribute('aria-disabled', 'true')
    expect(tab).toHaveTextContent('Em breve')
    expect(tab).toHaveAccessibleDescription(/A análise por link ainda não está disponível/)
    await userEvent.click(tab)
    expect(screen.getByRole('tab', { name: 'Colar texto', selected: true })).toBeInTheDocument()
    expect(screen.queryByLabelText('Endereço completo da notícia')).not.toBeInTheDocument()
  })

  it('o contador mostra o excesso por escrito e nada é cortado na colagem (RF01)', async () => {
    setup()
    const long = 'a'.repeat(TEXT_LIMITS.max + 1)
    await userEvent.click(textarea())
    await userEvent.paste(long)
    expect(textarea()).toHaveValue(long)
    expect(
      screen.getByText(
        new RegExp(`${formatNumber(TEXT_LIMITS.max + 1)} \\/ ${formatNumber(TEXT_LIMITS.max)} · 1 a mais`)
      )
    ).toBeInTheDocument()
  })
})

describe('RF24: só a opção escolhida vai na solicitação', () => {
  it('orienta link no campo de texto sem enviar ou consumir análise e permite corrigir a aba', async () => {
    const { fetchImpl, services } = setup()
    const url = 'https://noticias.uol.com.br/colunas/thais-bilenky/2026/10/14/ia-da-meta-bandeira-lula-e-flavio-bolsonaro.htm'
    await userEvent.click(textarea())
    await userEvent.paste(url)
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent('Você colou um link no campo de texto.')
    expect(queryErrorAlert()).toHaveTextContent('Use a aba Inserir link')
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
    expect(textarea()).toHaveFocus()
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.click(screen.getByLabelText('Endereço completo da notícia'))
    await userEvent.paste(url)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(bodyOf(fetchImpl)).toEqual({ input_type: 'url', url })
  })

  it('na aba de texto, envia só o texto', async () => {
    const { fetchImpl } = setup()
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(bodyOf(fetchImpl)).toEqual({ input_type: 'text', text: VALID_TEXT })
  })

  it('na aba de link, envia só o endereço', async () => {
    const { fetchImpl } = setup()
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.type(screen.getByLabelText('Endereço completo da notícia'), 'https://exemplo.com/noticia')
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(bodyOf(fetchImpl)).toEqual({ input_type: 'url', url: 'https://exemplo.com/noticia' })
  })

  it('o que foi digitado na outra aba não é enviado, mas fica no rascunho', async () => {
    const { fetchImpl } = setup()
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.type(screen.getByLabelText('Endereço completo da notícia'), 'https://exemplo.com/a')
    await userEvent.click(screen.getByRole('tab', { name: 'Colar texto' }))
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    expect(screen.getByLabelText('Endereço completo da notícia')).toHaveValue('https://exemplo.com/a')
    await userEvent.click(screen.getByRole('tab', { name: 'Colar texto' }))
    expect(textarea()).toHaveValue(VALID_TEXT)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(bodyOf(fetchImpl)).toEqual({ input_type: 'text', text: VALID_TEXT })
  })

  it('o texto é normalizado antes de seguir (espaços das pontas, quebras de linha repetidas)', async () => {
    const { fetchImpl } = setup()
    await userEvent.click(textarea())
    await userEvent.paste(`   ${VALID_TEXT}   `)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(bodyOf(fetchImpl).text).toBe(VALID_TEXT)
  })
})

describe('validação no navegador (RF01, RF27)', () => {
  it('texto curto: erro escrito, foco no campo, nada é enviado e o limite não é gasto', async () => {
    const { fetchImpl, services } = setup()
    await userEvent.type(textarea(), 'oi, vi uma notícia estranha')
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('Precisamos de um pouco mais de texto.')
    expect(alert).toHaveTextContent('Seu texto tem 27 caracteres')
    expect(textarea()).toHaveFocus()
    expect(textarea()).toHaveAttribute('aria-invalid', 'true')
    expect(textarea()).toHaveAccessibleDescription(/Precisamos de um pouco mais de texto/)
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
  })

  it('campo vazio também é recusado antes do envio', async () => {
    const { fetchImpl } = setup()
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent('Precisamos de um pouco mais de texto.')
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('texto acima do limite máximo: avisa o limite, não corta e não envia', async () => {
    const { fetchImpl } = setup()
    await userEvent.click(textarea())
    await userEvent.paste('a'.repeat(TEXT_LIMITS.max + 1))
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('O texto passou do limite.')
    expect(alert).toHaveTextContent('Nada foi cortado')
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(textarea()).toHaveValue('a'.repeat(TEXT_LIMITS.max + 1))
  })

  it.each([
    ['', 'Falta o endereço da notícia.'],
    ['exemplo.com/noticia', 'Esse endereço não parece válido.'],
    ['ftp://exemplo.com/noticia', 'Esse endereço não parece válido.'],
  ])('endereço "%s": mostra "%s" e leva o foco ao campo', async (value, title) => {
    const { fetchImpl } = setup()
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    const field = screen.getByLabelText('Endereço completo da notícia')
    if (value) await userEvent.type(field, value)
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent(title)
    expect(screen.getByLabelText('Endereço completo da notícia')).toHaveFocus()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('o erro some quando a pessoa volta a digitar', async () => {
    setup()
    await userEvent.click(submit())
    await findErrorAlert()
    await userEvent.type(textarea(), 'a')
    expect(queryErrorAlert()).not.toBeInTheDocument()
  })

  it('"Corrigir o conteúdo" devolve o foco ao campo', async () => {
    setup()
    await userEvent.click(submit())
    await findErrorAlert()
    screen.getByRole('button', { name: 'Corrigir o conteúdo' }).focus()
    await userEvent.click(screen.getByRole('button', { name: 'Corrigir o conteúdo' }))
    expect(textarea()).toHaveFocus()
  })
})

describe('texto de exemplo', () => {
  it('preenche o campo, atualiza o contador e leva o foco ao texto', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: /Testar com um exemplo/ }))
    expect(textarea()).toHaveValue(EXAMPLE_TEXT)
    expect(textarea()).toHaveFocus()
    expect(screen.getByText(`${EXAMPLE_TEXT.length} / ${formatNumber(TEXT_LIMITS.max)}`)).toBeInTheDocument()
  })

  it('não aparece na aba de link', async () => {
    setup()
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    expect(screen.queryByRole('button', { name: /Testar com um exemplo/ })).not.toBeInTheDocument()
  })

  it('o exemplo enviado conta como análise comum (também entra no limite)', async () => {
    const { services } = setup()
    await userEvent.click(screen.getByRole('button', { name: /Testar com um exemplo/ }))
    await userEvent.click(submit())
    await screen.findByText(/RESULTADO/)
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max - 1)
  })
})

describe('RF25 e RNF17: espera da análise', () => {
  it('RNF17: a confirmação aparece no mesmo clique, antes da resposta, com o foco no título', async () => {
    const { fetchImpl } = deferredFetch()
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const heading = screen.getByRole('heading', { name: 'Recebemos o seu conteúdo.' })
    expect(heading).toHaveFocus()
    expect(screen.getByText(/leva até 30 segundos/)).toBeInTheDocument()
    expect(screen.getByText(/Validação do conteúdo/)).toBeInTheDocument()
    expect(screen.getByText(/Análise do texto/)).toBeInTheDocument()
  })

  it('RF25: durante a espera não existe botão de envio (nenhuma solicitação duplicada)', async () => {
    const { fetchImpl, respond } = deferredFetch()
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    expect(screen.queryByRole('button', { name: /Verificar agora/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    await act(async () => respond(created()))
    await screen.findByText(/RESULTADO/)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('RF25: não mostra barra de progresso nem etapas que a interface não conhece', async () => {
    const { fetchImpl } = deferredFetch()
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Etapas conhecidas' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(2)
    expect(within(steps).getByText('concluída')).toBeInTheDocument()
    expect(within(steps).getByText('em andamento')).toBeInTheDocument()
  })

  it('cancelar interrompe a requisição, mantém o texto, devolve o foco ao campo e não gasta o limite', async () => {
    const { fetchImpl, signals } = deferredFetch()
    const { services } = setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar análise' }))
    expect(signals[0].aborted).toBe(true)
    await waitFor(() => expect(textarea()).toHaveValue(VALID_TEXT))
    await waitFor(() => expect(textarea()).toHaveFocus())
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
    expect(queryErrorAlert()).not.toBeInTheDocument()
  })

  it('sucesso: abre o resultado pelo identificador, conta no limite e guarda no histórico', async () => {
    const { services } = setup()
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    expect(await screen.findByText('RESULTADO 7b0f7a48-2f0d-4c64-9a36-3e1d3a0c5a11')).toBeInTheDocument()
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max - 1)
    expect(services.history.getSnapshot().items).toHaveLength(1)
  })

  it('o texto enviado nunca vai para o armazenamento do navegador (RF05)', async () => {
    const { services } = setup()
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await screen.findByText(/RESULTADO/)
    const stored = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
    expect(stored).not.toContain('transporte coletivo')
    expect(JSON.stringify(services.history.getSnapshot())).not.toContain('novos horários')
  })
})

describe('RF33: limite de visitante', () => {
  const clock = () => ({ now: Date.UTC(2026, 9, 8, 12, 0, 0) })

  function useUp(services) {
    for (let i = 0; i < VISITOR_LIMIT.max; i += 1) services.visitorLimit.registerCounted()
  }

  it('o medidor acompanha o uso: a cada análise concluída sobra uma a menos', async () => {
    const { services } = setup({ clock: clock() })
    services.visitorLimit.registerCounted()
    await waitFor(() => expect(screen.getByText(/2 de 3/)).toBeInTheDocument())
    expect(screen.getByText(/renovação em 24 h/)).toBeInTheDocument()
  })

  it('a quarta tentativa não inicia processamento e mostra quando o limite renova', async () => {
    const { services, fetchImpl } = setup({ clock: clock() })
    useUp(services)
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const dialog = await screen.findByRole('dialog', { name: 'Você chegou ao limite de análises.' })
    expect(dialog).toHaveTextContent('3 análises a cada 24 horas')
    expect(dialog).toHaveTextContent('09/10 às 09:00')
    expect(dialog).toHaveTextContent('daqui a 24 h')
    expect(within(dialog).getByRole('link', { name: 'Entrar' })).toHaveAttribute('href', '/entrar')
    expect(within(dialog).getByRole('link', { name: /Criar conta/ })).toHaveAttribute('href', '/criar-conta')
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: 'Recebemos o seu conteúdo.' })).not.toBeInTheDocument()
  })

  it('o aviso do limite vem antes da validação (corrigir o texto não ajudaria agora)', async () => {
    const { services } = setup({ clock: clock() })
    useUp(services)
    await userEvent.click(submit())
    expect(await screen.findByRole('dialog', { name: 'Você chegou ao limite de análises.' })).toBeInTheDocument()
    expect(screen.queryByText('Precisamos de um pouco mais de texto.')).not.toBeInTheDocument()
  })

  it('"Agora não" fecha o aviso, devolve o foco e mantém o que foi digitado', async () => {
    const { services } = setup({ clock: clock() })
    useUp(services)
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Agora não' })).toHaveFocus()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Agora não' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(textarea()).toHaveValue(VALID_TEXT)
    expect(submit()).toHaveFocus()
  })

  it('"Criar conta" leva à página de cadastro', async () => {
    const { services } = setup({ clock: clock() })
    useUp(services)
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('link', { name: /Criar conta/ }))
    expect(await screen.findByText('PÁGINA CRIAR CONTA')).toBeInTheDocument()
  })

  it('sem contas disponíveis, o aviso só orienta a esperar (sem links para entrar ou criar conta)', async () => {
    const { services } = setup({ clock: clock(), env: { VITE_ACCOUNTS_MODE: 'off' } })
    useUp(services)
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByRole('link')).not.toBeInTheDocument()
    expect(dialog).toHaveTextContent('Não há como criar conta nesta versão')
  })

  it('passadas 24 horas da primeira análise, o visitante pode analisar de novo', async () => {
    const time = clock()
    const { services, fetchImpl } = setup({ clock: time })
    useUp(services)
    time.now += VISITOR_LIMIT.windowMs + 1_000
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
  })

  it('quem está com a conta conectada não tem o limite de visitante', async () => {
    const storage = createTestServices().storage
    const auth = createDemoAuthGateway({ storage })
    await auth.signIn({ email: 'a@b.co', password: '12345678' })
    const { services, fetchImpl } = setup({ clock: clock(), auth })
    useUp(services)
    expect(screen.getByText('Conta conectada: sem limite de visitante.')).toBeInTheDocument()
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('RF27: erros da API na tela do formulário', () => {
  it.each(['paywall_or_forbidden', 'empty_scraped_text'])('%s permite continuar colando o texto sem consumir a cota', async (code) => {
    const fetchImpl = vi.fn(async () => jsonResponse(makeApiError({ code, field: 'url' }), { status: 400 }))
    const { services } = setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.type(screen.getByLabelText('Endereço completo da notícia'), 'https://exemplo.com/noticia')
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent('Nenhuma análise foi feita só com o endereço.')
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
    await userEvent.click(screen.getByRole('button', { name: 'Colar o texto da notícia' }))
    expect(screen.getByRole('tab', { name: 'Colar texto', selected: true })).toBeInTheDocument()
    expect(textarea()).toHaveFocus()
    expect(textarea()).toHaveValue(VALID_TEXT)
    expect(queryErrorAlert()).not.toBeInTheDocument()
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('timeout do site oferece nova tentativa com o mesmo link', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(jsonResponse(makeApiError({ code: 'url_timeout', field: 'url' }), { status: 400 }))
      .mockResolvedValueOnce(created(makeApiAnalysis({ input_type: 'url' })))
    const { services } = setup({ fetchImpl })
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.type(screen.getByLabelText('Endereço completo da notícia'), 'https://exemplo.com/noticia')
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('O site demorou para responder.')
    expect(alert).not.toHaveTextContent('30 segundos')
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
    await userEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    await screen.findByText(/RESULTADO/)
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(bodyOf(fetchImpl, 1)).toEqual({ input_type: 'url', url: 'https://exemplo.com/noticia' })
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max - 1)
  })

  it('endereço interno orienta usar site público e permite corrigir o link', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(makeApiError({ code: 'forbidden_url', field: 'url' }), { status: 400 }))
    setup({ fetchImpl })
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    const input = screen.getByLabelText('Endereço completo da notícia')
    await userEvent.type(input, 'http://127.0.0.1/noticia')
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent('site público')
    await userEvent.click(screen.getByRole('button', { name: 'Corrigir o conteúdo' }))
    const returnedInput = screen.getByLabelText('Endereço completo da notícia')
    expect(returnedInput).toHaveFocus()
    expect(returnedInput).toHaveValue('http://127.0.0.1/noticia')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('idioma não suportado: explica, leva o foco ao campo e não gasta o limite', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(apiErrors.unsupportedLanguage, { status: 400 }))
    const { services } = setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('O Apura só analisa textos em português.')
    expect(alert).not.toHaveTextContent('Fake Eyes')
    await waitFor(() => expect(textarea()).toHaveFocus())
    expect(services.visitorLimit.remaining()).toBe(VISITOR_LIMIT.max)
  })

  it('serviço indisponível: o painel recebe o foco e "Tentar de novo" reenvia o mesmo conteúdo', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(apiErrors.analysisUnavailable, { status: 503 }))
      .mockResolvedValueOnce(created())
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('O serviço de análise está indisponível.')
    expect(alert.closest('[data-scenario="api_unavailable"]')).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    await screen.findByText(/RESULTADO/)
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(bodyOf(fetchImpl, 1)).toEqual(bodyOf(fetchImpl, 0))
  })

  it('rede fora do ar com o navegador "online": não culpa a conexão da pessoa, que não dá para saber', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('O serviço de análise está indisponível.')
    expect(alert).toHaveTextContent('O problema não está no seu texto')
    expect(alert).not.toHaveTextContent('Confira sua conexão')
  })

  it('sem conexão (o navegador diz que está offline): diz que o problema é a conexão', async () => {
    const online = vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
    try {
      const fetchImpl = vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      })
      setup({ fetchImpl })
      await userEvent.type(textarea(), VALID_TEXT)
      await userEvent.click(submit())
      expect(await findErrorAlert()).toHaveTextContent('Confira sua conexão com a internet')
    } finally {
      online.mockRestore()
    }
  })

  it('link ainda indisponível na API (501): oferece colar o texto, que troca de aba e leva o foco', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(apiErrors.urlUnavailable, { status: 501 }))
    setup({ fetchImpl })
    await userEvent.click(screen.getByRole('tab', { name: 'Inserir link' }))
    await userEvent.type(screen.getByLabelText('Endereço completo da notícia'), 'https://exemplo.com/noticia')
    await userEvent.click(submit())
    const alert = await findErrorAlert()
    expect(alert).toHaveTextContent('A análise por link ainda não está disponível.')
    await userEvent.click(screen.getByRole('button', { name: 'Colar o texto da notícia' }))
    expect(screen.getByRole('tab', { name: 'Colar texto', selected: true })).toBeInTheDocument()
    expect(textarea()).toHaveFocus()
    expect(queryErrorAlert()).not.toBeInTheDocument()
  })

  it('limite de requisições do servidor (429): avisa quanto esperar', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(apiErrors.throttled, { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '12' } }),
    )
    setup({ fetchImpl })
    await userEvent.type(textarea(), VALID_TEXT)
    await userEvent.click(submit())
    expect(await findErrorAlert()).toHaveTextContent('Aguarde cerca de 12 segundos')
  })
})
