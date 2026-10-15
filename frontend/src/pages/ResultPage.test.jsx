import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { normalizeAnalysis } from '../domain/analysis.js'
import { apiErrors, apiHigh, apiInconclusive, apiLow, makeApiAnalysis } from '../test/fixtures.js'
import { createTestServices, jsonResponse, renderWithApp } from '../test/render.jsx'
import ResultPage from './ResultPage.jsx'

// RF16 (status e índice), RF17 (explicação, fontes, limitações), RF18 (próximo passo e resumo),
// RF19 (feedback), RF26 (resultado antes dos detalhes técnicos) e RF29 (resultado recuperado por id).

const ID = '7b0f7a48-2f0d-4c64-9a36-3e1d3a0c5a11'

/**
 * Abre a página de resultado com a análise já no cache da página (acabou de chegar da API).
 * @param {Record<string, unknown>} body resposta da API
 * @param {Parameters<typeof createTestServices>[0]} [options]
 */
function openCached(body, options = {}) {
  const services = createTestServices(options)
  const analysis = normalizeAnalysis(body)
  services.results.put(analysis)
  const utils = renderWithApp(
    <Routes>
      <Route path="/resultado/:id" element={<ResultPage />} />
    </Routes>,
    { route: `/resultado/${analysis.id}`, services },
  )
  return { services, analysis, ...utils }
}

/** Abre a página sem cache: o resultado vem de GET /api/v1/analyses/{id}/. */
function openFromApi(fetchImpl, options = {}) {
  const services = createTestServices({ fetchImpl, ...options })
  const utils = renderWithApp(
    <Routes>
      <Route path="/resultado/:id" element={<ResultPage />} />
    </Routes>,
    { route: `/resultado/${ID}`, services },
  )
  return { services, ...utils }
}

const headings = () => screen.getAllByRole('heading').map((h) => h.textContent.trim())

const SOURCE = {
  id: 's1',
  relation: 'compatible',
  publisher: 'Agência de checagem',
  title: 'Prefeitura confirma novos horários',
  excerpt: 'A prefeitura confirmou os novos horários das linhas.',
  published_at: '2026-10-07T09:00:00Z',
  url: 'https://checagem.example.org/horarios',
  relation_reason: 'Trata do mesmo anúncio da prefeitura.',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RF26: o resultado principal vem antes dos detalhes técnicos', () => {
  it('ordem dos blocos na página', () => {
    openCached(makeApiAnalysis())
    const order = headings()
    const at = (title) => {
      const index = order.indexOf(title)
      expect(index, `título ausente: ${title}`).toBeGreaterThanOrEqual(0)
      return index
    }
    const verdict = at('Requer atenção')
    const next = at('Pause antes de repassar.')
    const why = at('Por que esse resultado?')
    const sources = at('Fontes consultadas')
    const indicators = at('Indicadores de linguagem')
    const limits = at('Limitações')
    expect(verdict).toBeLessThan(next)
    expect(next).toBeLessThan(why)
    expect(why).toBeLessThan(sources)
    expect(sources).toBeLessThan(indicators)
    expect(indicators).toBeLessThan(limits)
    // A área técnica é um bloco recolhido no fim da coluna principal.
    const technical = screen.getByText('Detalhes técnicos')
    const limitsHeading = screen.getByRole('heading', { name: 'Limitações' })
    expect(limitsHeading.compareDocumentPosition(technical) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('compartilhar e avaliar ficam numa região lateral própria', () => {
    openCached(makeApiAnalysis())
    const side = screen.getByRole('complementary', { name: 'Compartilhar e avaliar' })
    expect(within(side).getByRole('heading', { name: 'Compartilhar com cuidado' })).toBeInTheDocument()
    expect(within(side).getByRole('heading', { name: 'A explicação ajudou?' })).toBeInTheDocument()
  })

  it('os detalhes técnicos começam fechados', () => {
    openCached(makeApiAnalysis())
    const details = screen.getByText('Detalhes técnicos').closest('details')
    expect(details).not.toHaveAttribute('open')
  })

  it('as limitações estão na página principal, sem abrir a área técnica (RF17)', () => {
    openCached(makeApiAnalysis())
    const limitations = screen.getByRole('heading', { name: 'Limitações' }).closest('section')
    expect(limitations).toHaveTextContent('O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.')
    expect(limitations.closest('details')).toBeNull()
  })
})

describe('RF16: status e índice', () => {
  it.each([
    ['poucos sinais de risco', apiLow, 'Poucos sinais de risco', '18,4', 'Confira a origem.'],
    ['requer atenção', makeApiAnalysis, 'Requer atenção', '48,31', 'Pause antes de repassar.'],
    ['alto risco', apiHigh, 'Alto risco', '88,1', 'Pause antes de repassar.'],
  ])('%s: mostra o rótulo, o índice e o aviso de que não é probabilidade', (_name, make, label, index, nextStep) => {
    const { container } = openCached(make())
    expect(screen.getByRole('heading', { level: 2, name: label })).toBeInTheDocument()
    expect(container.querySelector('.risk-scale__number')).toHaveTextContent(new RegExp(`^${index}$`))
    expect(screen.getByText('O índice é um indicador de risco. Ele não é a probabilidade de a notícia ser falsa nem uma certeza.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: nextStep })).toBeInTheDocument()
  })

  it('o status também é escrito dentro do selo (não depende da cor)', () => {
    const { container } = openCached(apiHigh())
    expect(container.querySelector('.pill')).toHaveTextContent('Alto risco')
  })

  it('a escala destaca, por escrito, a faixa do resultado e informa as faixas do RF16', () => {
    openCached(makeApiAnalysis())
    const legend = screen.getByRole('list', { name: 'Faixas do índice de risco' })
    const items = within(legend).getAllByRole('listitem')
    expect(items.map((li) => li.textContent.replace(/\s+/g, ' ').trim())).toEqual([
      '0 a 25Poucos sinais de risco',
      'Acima de 25 até 60Requer atenção (faixa deste resultado)',
      'Acima de 60 até 100Alto risco',
    ])
    expect(items[1]).toHaveAttribute('aria-current', 'true')
  })

  it('exibe a probabilidade calculada pelo modelo com destaque na tela', () => {
    const { container } = openCached(makeApiAnalysis())
    expect(screen.getByText('Probabilidade calculada pelo modelo')).toBeInTheDocument()
    expect(container.querySelector('.model-prob-card__headline')).toHaveTextContent(/62% de chance de ser falsa/)
    expect(screen.getByText('Confiança estatística: 86%')).toBeInTheDocument()
    expect(screen.getByText(/Chance de ser verdadeira:/)).toBeInTheDocument()
    expect(screen.getByText(/Chance de ser falsa:/)).toBeInTheDocument()
  })

  it('exibe alerta de estilo formal e divergência factual quando a notícia é formal mas diverge do consenso', () => {
    const { container } = openCached(
      makeApiAnalysis({
        status: { code: 'requer_atencao', label: 'Requer atenção' },
        risk_index: 35,
        model: {
          ...makeApiAnalysis().model,
          fake_probability: 0.001,
          confidence: 0.999,
          is_out_of_domain: true,
          training_scope: 'out_of_domain_disinformation',
          discourse_type: 'sensacionalismo',
          discourse_label: 'Sensacionalismo / Apelativo',
          verdict_tendency: 'alto_risco_falsa',
          semantic_comparison: {
            consensus_status: 'diverge_consenso',
            consensus_summary: 'As alegações divergem da realidade dos fatos apurados.',
          },
        },
      }),
    )
    expect(screen.getByText('Fora do Escopo de Treino do Modelo')).toBeInTheDocument()
    expect(screen.getByText('Sensacionalismo / Apelativo')).toBeInTheDocument()
    expect(container.querySelector('.model-prob-card__headline')).toHaveTextContent(/99,9% de estilo formal/)
    expect(container.querySelector('.model-prob-card__discrepant-badge')).toHaveTextContent('(conteúdo contestado)')
    expect(screen.getByText(/Padrão de escrita formal:/)).toBeInTheDocument()
    expect(screen.getByText('Diverge do Consenso')).toBeInTheDocument()
    expect(screen.getByText('As alegações divergem da realidade dos fatos apurados.')).toBeInTheDocument()
    expect(screen.getByText(/Não confie apenas no estilo de escrita/)).toBeInTheDocument()
  })

  it('análise inconclusiva: sem índice, sem escala, e diz que não é veredito', () => {
    openCached(apiInconclusive())
    expect(screen.getByRole('heading', { level: 2, name: 'Análise inconclusiva' })).toBeInTheDocument()
    expect(screen.getByText('Sem índice')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Faixas do índice de risco' })).not.toBeInTheDocument()
    expect(screen.getByText(/Isso não quer dizer que a notícia seja verdadeira nem que seja falsa/)).toBeInTheDocument()
    expect(screen.queryByText(/não é a probabilidade de a notícia ser falsa nem uma certeza/)).not.toBeInTheDocument()
  })

  it('RF16: motivo de abstenção tem prioridade — mesmo que a API mande "alto risco", a tela mostra inconclusiva', () => {
    openCached(
      makeApiAnalysis({
        status: { code: 'alto_risco', label: 'Alto risco' },
        risk_index: 90,
        abstention: [{ code: 'source_conflict', message: 'As fontes consultadas se contradizem.' }],
      }),
    )
    expect(screen.getByRole('heading', { level: 2, name: 'Análise inconclusiva' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Alto risco' })).not.toBeInTheDocument()
  })

  it('mostra a alegação analisada e avisa que o resumo é automático, sem prometer edição que não existe', () => {
    openCached(makeApiAnalysis())
    expect(screen.getByText('“Todas as linhas de ônibus deixarão de funcionar no próximo domingo.”')).toBeInTheDocument()
    expect(screen.getByText(/Ainda não é possível confirmar ou corrigir a alegação nesta versão/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /confirmar|corrigir/i })).not.toBeInTheDocument()
  })

  it('texto analisado só em parte: avisa quantos trechos foram analisados', () => {
    openCached(
      makeApiAnalysis({
        model: { ...makeApiAnalysis().model, fully_analyzed: false, chunks_analyzed: 2, chunks_total: 5 },
      }),
    )
    expect(screen.getByText('Só uma parte do texto foi analisada.')).toBeInTheDocument()
    expect(screen.getByText(/Foram analisados 2 de 5 trechos\./)).toBeInTheDocument()
  })

  it('texto analisado por inteiro: não mostra o aviso de análise parcial', () => {
    openCached(makeApiAnalysis())
    expect(screen.queryByText('Só uma parte do texto foi analisada.')).not.toBeInTheDocument()
  })
})

describe('RF17: explicação', () => {
  it('lista os fatores vindos da API em linguagem simples', () => {
    openCached(makeApiAnalysis())
    const section = screen.getByRole('heading', { name: 'Por que esse resultado?' }).closest('section')
    expect(within(section).getAllByRole('listitem')).toHaveLength(3)
    expect(section).toHaveTextContent('Foram encontradas expressões apelativas')
  })

  it('inconclusiva: o motivo da abstenção vem primeiro e não se repete como fator', () => {
    openCached(apiInconclusive())
    const section = screen.getByRole('heading', { name: 'Por que não foi possível concluir' }).closest('section')
    const items = within(section).getAllByRole('listitem')
    expect(items).toHaveLength(1)
    expect(items[0]).toHaveTextContent('O modelo não teve segurança estatística suficiente')
  })

  it('sem explicação na resposta: diz que não veio, em vez de deixar a seção vazia', () => {
    openCached(makeApiAnalysis({ explanation: [] }))
    expect(screen.getByText('Esta resposta não trouxe uma explicação em texto.')).toBeInTheDocument()
  })

  it('indicadores linguísticos: números, termos apelativos e o aviso de que não são prova (RF10)', () => {
    openCached(makeApiAnalysis())
    const section = screen.getByRole('heading', { name: 'Indicadores de linguagem' }).closest('section')
    expect(section).toHaveTextContent('Sozinhos, eles não provam que o conteúdo é verdadeiro nem que é falso.')
    expect(section).toHaveTextContent('8% das palavras com 3 letras ou mais')
    const chips = within(within(section).getByRole('list', { name: 'Expressões apelativas encontradas' })).getAllByRole('listitem')
    expect(chips.map((c) => c.textContent)).toEqual(['urgente', 'compartilhe'])
  })

  it('indicadores sem termos apelativos: escreve "Nenhuma encontrada"', () => {
    const body = makeApiAnalysis()
    openCached({ ...body, indicators: { ...body.indicators, sensational_terms: [] } })
    expect(screen.getByText('Nenhuma encontrada')).toBeInTheDocument()
  })
})

describe('RF07, RF08, RF27: fontes e evidências', () => {
  const section = () => screen.getByRole('heading', { name: 'Fontes consultadas' }).closest('section')

  it('consulta desligada no back end (hoje): diz que nenhuma evidência externa foi verificada', () => {
    openCached(makeApiAnalysis())
    expect(section()).toHaveTextContent('a consulta a fontes externas ainda não está habilitada')
    expect(section()).toHaveTextContent('Nenhuma evidência externa foi verificada')
    expect(within(section()).queryByRole('article')).not.toBeInTheDocument()
  })

  it('consultou e não achou: "evidências insuficientes", sem inventar referência', () => {
    openCached(makeApiAnalysis({ evidence: { enabled: true, sources: [] } }))
    expect(section()).toHaveTextContent('as evidências são insuficientes')
    expect(section()).toHaveTextContent('Não vamos inventar referências')
  })

  it('achou fontes: cartão com veículo, data, trecho, relação, motivo e link para abrir', () => {
    openCached(makeApiAnalysis({ evidence: { enabled: true, sources: [SOURCE] } }))
    const card = within(section()).getByRole('article')
    expect(card).toHaveTextContent('Compatível com a alegação')
    expect(card).toHaveTextContent('Prefeitura confirma novos horários')
    expect(card).toHaveTextContent('Agência de checagem')
    expect(card).toHaveTextContent('07/10/2026')
    expect(card).toHaveTextContent('“A prefeitura confirmou os novos horários das linhas.”')
    expect(card).toHaveTextContent('Por que esta fonte aparece: Trata do mesmo anúncio da prefeitura.')
    const link = within(card).getByRole('link', { name: /Abrir a fonte \(checagem\.example\.org\)/ })
    expect(link).toHaveAttribute('href', 'https://checagem.example.org/horarios')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toMatch(/noopener/)
    expect(link.getAttribute('rel')).toMatch(/noreferrer/)
  })

  it('campo que a fonte não trouxe aparece como "não informado", nunca inventado', () => {
    openCached(
      makeApiAnalysis({ evidence: { enabled: true, sources: [{ id: 's2', relation: 'contextual' }] } }),
    )
    const card = within(section()).getByRole('article')
    expect(card).toHaveTextContent('Título não informado')
    expect(card).toHaveTextContent('Veículo ou instituição não informado')
    expect(card).toHaveTextContent('Data não informada')
    expect(card).toHaveTextContent('Trecho utilizado não informado.')
    expect(card).toHaveTextContent('motivo não informado.')
    expect(card).toHaveTextContent('Endereço da fonte não informado.')
    expect(within(card).queryByRole('link')).not.toBeInTheDocument()
  })

  it('endereço que não é http(s) é descartado (RNF16: conteúdo externo não é confiável)', () => {
    openCached(
      makeApiAnalysis({ evidence: { enabled: true, sources: [{ ...SOURCE, url: 'javascript:alert(1)' }] } }),
    )
    const card = within(section()).getByRole('article')
    expect(within(card).queryByRole('link')).not.toBeInTheDocument()
    expect(card).toHaveTextContent('Endereço da fonte não informado.')
  })

  it('fonte sem relação demonstrável com a alegação não aparece (RF08)', () => {
    openCached(
      makeApiAnalysis({ evidence: { enabled: true, sources: [{ ...SOURCE, relation: 'qualquer-coisa' }] } }),
    )
    expect(within(section()).queryByRole('article')).not.toBeInTheDocument()
  })

  it.each([
    ['conflicting', 'Conflitante com a alegação'],
    ['contextual', 'Traz contexto'],
    ['insufficient', 'Insuficiente para confirmar ou contestar'],
  ])('relação "%s" é escrita por extenso', (relation, label) => {
    openCached(makeApiAnalysis({ evidence: { enabled: true, sources: [{ ...SOURCE, relation }] } }))
    expect(within(section()).getByRole('article')).toHaveTextContent(label)
  })

  it('falha na consulta (RF27, cenário 6): mantém o resultado e oferece nova análise', () => {
    const failed = makeApiAnalysis({ evidence: { enabled: true, sources: [], failed: true } })
    openCached(failed)
    expect(section()).toHaveTextContent('Não foi possível consultar todas as fontes.')
    expect(section()).toHaveTextContent('O resultado pode estar incompleto.')
    // O resultado continua na tela.
    expect(screen.getByRole('heading', { level: 2, name: 'Requer atenção' })).toBeInTheDocument()
    expect(within(section()).getByRole('link', { name: 'Iniciar nova análise' })).toHaveAttribute('href', '/')
    expect(section()).not.toHaveTextContent('Nenhuma fonte relevante foi encontrada')
  })

  it('consulta parcial: mostra as fontes disponíveis e avisa que outras podem faltar', () => {
    openCached(makeApiAnalysis({ evidence: { enabled: true, sources: [SOURCE], failed: true } }))
    expect(section()).toHaveTextContent('A consulta às fontes foi parcial.')
    expect(section()).toHaveTextContent('A lista pode estar incompleta.')
    expect(within(section()).getByRole('article')).toHaveTextContent('Prefeitura confirma novos horários')
    expect(within(section()).getByRole('link', { name: 'Iniciar nova análise' })).toHaveAttribute('href', '/')
  })
})

describe('RF21: detalhes técnicos', () => {
  it('abertos, trazem identificador, versões, saída do modelo e o cálculo do índice', async () => {
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByText('Detalhes técnicos'))
    const details = screen.getByText('Detalhes técnicos').closest('details')
    expect(details).toHaveAttribute('open')
    for (const text of [
      ID,
      'bertimbau-fakenews-v4',
      'rules-v1.0.0',
      'identity-v0 (a confiança do modelo não foi calibrada)',
      'classe “falsa” · pontuação bruta 0,62 · confiança 0,86 (não é a probabilidade de a notícia ser falsa)',
      'model_fake_probability: 0,62 · linguistic_indicators: 0,41',
      'model_fake_probability: 0,6 · linguistic_indicators: 0,15 · evidence_conflict: 0,25',
      'evidence_conflict',
      '100 * sum(w_i * s_i) / sum(w_i)',
      '1,2 s',
    ]) {
      expect(details).toHaveTextContent(text)
    }
  })

  it('a pontuação bruta do modelo nunca é chamada de probabilidade de ser falsa', async () => {
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByText('Detalhes técnicos'))
    const details = screen.getByText('Detalhes técnicos').closest('details')
    expect(details.textContent).not.toMatch(/probabilidade de ser falsa|chance de ser falsa/i)
  })
})

describe('RF18: resumo copiável', () => {
  function stubClipboard(writeText) {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  }
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('o resumo traz status, alegação, data, limitações, aviso de análise automática e sem verificação humana', async () => {
    openCached(makeApiAnalysis({ evidence: { enabled: true, sources: [SOURCE] } }))
    await userEvent.click(screen.getByText('Ver o texto do resumo'))
    const summary = document.querySelector('.share-text').textContent
    expect(summary).toContain('Status: Requer atenção')
    expect(summary).toContain('Índice de risco: 48,31 de 100 (é um indicador de risco, não a probabilidade de a notícia ser falsa).')
    expect(summary).toContain('Alegação analisada: “Todas as linhas de ônibus deixarão de funcionar no próximo domingo.”')
    expect(summary).toContain('Data da análise: 08/10/2026')
    expect(summary).toContain('Limitações:')
    expect(summary).toContain('Agência de checagem: Prefeitura confirma novos horários (compatível com a alegação) https://checagem.example.org/horarios')
    expect(summary).toContain('Não houve verificação humana.')
  })

  it('análise inconclusiva: o resumo não vira conclusão', async () => {
    openCached(apiInconclusive())
    await userEvent.click(screen.getByText('Ver o texto do resumo'))
    const summary = document.querySelector('.share-text').textContent
    expect(summary).toContain('Status: Análise inconclusiva')
    expect(summary).toContain('Índice de risco: não calculado nesta análise.')
    expect(summary).toContain('Não use este resumo para afirmar que a notícia é verdadeira nem que é falsa.')
  })

  it('copia o resumo para a área de transferência e avisa', async () => {
    const writeText = vi.fn(async () => {})
    stubClipboard(writeText)
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByRole('button', { name: 'Copiar resumo' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    expect(writeText.mock.calls[0][0]).toMatch(/^Apura: resumo da análise automática/)
    expect(await screen.findByText('Resumo copiado. Cole onde quiser compartilhar.')).toBeInTheDocument()
  })

  it('sem permissão para a área de transferência: mostra o texto selecionado para copiar à mão', async () => {
    stubClipboard(vi.fn(async () => Promise.reject(new DOMException('negado', 'NotAllowedError'))))
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByRole('button', { name: 'Copiar resumo' }))
    const area = await screen.findByLabelText('Texto do resumo')
    expect(area).toHaveAttribute('readonly')
    expect(area.value).toMatch(/^Apura: resumo da análise automática/)
    expect(screen.getByText(/Não foi possível copiar sozinho/)).toBeInTheDocument()
    await waitFor(() => expect(area).toHaveFocus())
    expect(area.selectionEnd - area.selectionStart).toBe(area.value.length)
  })

  it('navegador sem a API de área de transferência cai no mesmo caminho manual', async () => {
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByRole('button', { name: 'Copiar resumo' }))
    expect(await screen.findByLabelText('Texto do resumo')).toBeInTheDocument()
  })
})

describe('RF19: feedback', () => {
  it('antes de escolher, só pede a resposta (o comentário é opcional)', () => {
    openCached(makeApiAnalysis())
    const panel = screen.getByRole('heading', { name: 'A explicação ajudou?' }).closest('section')
    expect(within(panel).getByRole('group', { name: 'Avaliação da explicação' })).toBeInTheDocument()
    expect(within(panel).getByText(/Escolha uma resposta para continuar\. O comentário é opcional\./)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Enviar avaliação' })).not.toBeInTheDocument()
  })

  it('versão de demonstração: diz, antes do envio, que nada é enviado nem guardado', async () => {
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByRole('button', { name: 'Sim' }))
    expect(screen.getByRole('button', { name: 'Sim' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Não' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('Versão de demonstração: nada do que você escrever aqui é enviado nem guardado.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Quer contar mais\? \(opcional\)/)).toHaveAccessibleDescription(/Versão de demonstração/)
  })

  it('envia só a avaliação, sem comentário, e agradece sem fingir que guardou', async () => {
    openCached(makeApiAnalysis())
    await userEvent.click(screen.getByRole('button', { name: 'Não' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar avaliação' }))
    expect(await screen.findByText('Obrigado! Como esta é uma versão de demonstração, a avaliação não foi enviada nem guardada.')).toBeInTheDocument()
  })

  it('gateway real: envia id, avaliação e comentário (e só isso), e agradece de verdade', async () => {
    const submit = vi.fn(async () => ({ delivered: true }))
    openCached(makeApiAnalysis(), { feedback: { mode: 'real', submit } })
    await userEvent.click(screen.getByRole('button', { name: 'Sim' }))
    expect(screen.getByText(/O comentário é guardado por até/)).toBeInTheDocument()
    expect(screen.getByText(/O texto analisado não é enviado/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Quer contar mais/), '  Entendi bem.  ')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar avaliação' }))
    expect(await screen.findByText('Obrigado! Sua avaliação foi enviada.')).toBeInTheDocument()
    expect(submit).toHaveBeenCalledWith({ analysisId: ID, useful: true, comment: 'Entendi bem.' })
  })

  it('falha no envio: avisa, mantém o que a pessoa escreveu e deixa tentar de novo', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error('falha')).mockResolvedValueOnce({ delivered: true })
    openCached(makeApiAnalysis(), { feedback: { mode: 'real', submit } })
    await userEvent.click(screen.getByRole('button', { name: 'Sim' }))
    await userEvent.type(screen.getByLabelText(/Quer contar mais/), 'Ajudou.')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar avaliação' }))
    expect(await screen.findByText('Não foi possível enviar agora. Tente de novo em instantes.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Quer contar mais/)).toHaveValue('Ajudou.')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar avaliação' }))
    expect(await screen.findByText('Obrigado! Sua avaliação foi enviada.')).toBeInTheDocument()
    expect(submit).toHaveBeenCalledTimes(2)
  })

  it('comentário longo demais: explica por escrito e não deixa enviar', async () => {
    const submit = vi.fn(async () => ({ delivered: true }))
    openCached(makeApiAnalysis(), { feedback: { mode: 'real', submit } })
    await userEvent.click(screen.getByRole('button', { name: 'Sim' }))
    await userEvent.click(screen.getByLabelText(/Quer contar mais/))
    await userEvent.paste('a'.repeat(1001))
    expect(screen.getByText(/O comentário passou de 1\.000 caracteres\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enviar avaliação' })).toBeDisabled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('com o feedback desligado na configuração, o painel não aparece', () => {
    openCached(makeApiAnalysis(), { env: { VITE_FEEDBACK_MODE: 'off' } })
    expect(screen.queryByRole('heading', { name: 'A explicação ajudou?' })).not.toBeInTheDocument()
  })
})

describe('RF29: resultado recuperado pelo identificador', () => {
  it('sem cache (página recarregada, link do histórico): mostra o carregamento e depois o resultado', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(apiLow()))
    openFromApi(fetchImpl)
    expect(screen.getByText('Carregando o resultado…').closest('[role="status"]')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2, name: 'Poucos sinais de risco' })).toBeInTheDocument()
    expect(String(fetchImpl.mock.calls[0][0])).toMatch(new RegExp(`/api/v1/analyses/${ID}/$`))
    expect(document.title).toBe('Resultado da análise — Apura')
  })

  it('análise que não existe: explica e oferece verificar outro conteúdo ou abrir o histórico', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(apiErrors.notFound, { status: 404 }))
    openFromApi(fetchImpl)
    expect(await screen.findByRole('heading', { name: 'Análise não encontrada.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Iniciar nova análise' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Abrir o histórico' })).toHaveAttribute('href', '/historico')
    expect(document.title).toBe('Resultado indisponível — Apura')
  })

  it('serviço fora do ar: "Tentar de novo" busca outra vez e mostra o resultado', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(apiErrors.analysisUnavailable, { status: 503 }))
      .mockResolvedValueOnce(jsonResponse(apiHigh()))
    openFromApi(fetchImpl)
    expect(await screen.findByRole('heading', { name: 'O serviço de análise está indisponível.' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Alto risco' })).toBeInTheDocument()
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('resposta de uma versão de API que esta tela não conhece: pede para recarregar, sem mostrar dado errado', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ ...makeApiAnalysis(), api_version: 'v9' }))
    openFromApi(fetchImpl)
    expect(await screen.findByRole('heading', { name: 'Esta página está desatualizada.' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Recarregar a página' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Requer atenção' })).not.toBeInTheDocument()
  })

  it('o resultado fica no cache: abrir de novo não chama a API', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(apiLow()))
    const { services, unmount } = openFromApi(fetchImpl)
    await screen.findByRole('heading', { level: 2, name: 'Poucos sinais de risco' })
    unmount()
    renderWithApp(
      <Routes>
        <Route path="/resultado/:id" element={<ResultPage />} />
      </Routes>,
      { route: `/resultado/${ID}`, services },
    )
    expect(await screen.findByRole('heading', { level: 2, name: 'Poucos sinais de risco' })).toBeInTheDocument()
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

describe('acessibilidade da página de resultado (axe)', () => {
  it.each([
    ['requer atenção', () => makeApiAnalysis()],
    ['poucos sinais', apiLow],
    ['alto risco', apiHigh],
    ['inconclusiva', apiInconclusive],
    ['com fontes', () => makeApiAnalysis({ evidence: { enabled: true, sources: [SOURCE] } })],
    ['com falha nas fontes', () => makeApiAnalysis({ evidence: { enabled: true, sources: [], failed: true } })],
  ])('%s: sem violações', async (_name, make) => {
    const { container } = openCached(make())
    await act(async () => {})
    expect(await axe(container)).toHaveNoViolations()
  })
})
