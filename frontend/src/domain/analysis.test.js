import { describe, expect, it } from 'vitest'
import { apiHigh, apiInconclusive, apiLow, makeApiAnalysis } from '../test/fixtures.js'
import { AppError } from './errors.js'
import { normalizeAnalysis, normalizeSource, safeHttpUrl, statusOf } from './analysis.js'

const thrown = (fn) => {
  try {
    fn()
  } catch (error) {
    return error
  }
  return null
}

describe('normalizeAnalysis (RF29: contrato com a API v1)', () => {
  it('lê uma resposta de "requer atenção" para o formato da interface', () => {
    const a = normalizeAnalysis(makeApiAnalysis())
    expect(a.id).toBe('7b0f7a48-2f0d-4c64-9a36-3e1d3a0c5a11')
    expect(a.apiVersion).toBe('v1')
    expect(a.status).toEqual({ code: 'requer_atencao', label: 'Requer atenção' })
    expect(a.riskIndex).toBe(48.31)
    expect(a.claim.summary).toMatch(/linhas de ônibus/)
    expect(a.claim.confirmedByUser).toBe(false)
    expect(a.explanation).toHaveLength(3)
    expect(a.limitations).toHaveLength(4)
    expect(a.recommendations).toHaveLength(4)
    expect(a.indicators.sensationalTerms).toEqual(['urgente', 'compartilhe'])
    expect(a.versions.model).toBe('bertimbau-fakenews-v4')
    expect(a.model.calibrated).toBe(false)
    expect(a.risk.signalsMissing).toEqual(['evidence_conflict'])
    expect(statusOf(a)).toBe('requer_atencao')
  })

  it('lê as três faixas de risco e a análise inconclusiva', () => {
    expect(statusOf(normalizeAnalysis(apiLow()))).toBe('poucos_sinais_de_risco')
    expect(statusOf(normalizeAnalysis(apiHigh()))).toBe('alto_risco')
    const inc = normalizeAnalysis(apiInconclusive())
    expect(statusOf(inc)).toBe('analise_inconclusiva')
    expect(inc.riskIndex).toBeNull()
    expect(inc.abstention).toEqual([
      { code: 'low_confidence', message: 'O modelo não teve segurança estatística suficiente para indicar um nível de risco.' },
    ])
  })

  it('RF16: resposta com motivo de abstenção nunca aparece como risco', () => {
    const raw = makeApiAnalysis({
      status: { code: 'alto_risco', label: 'Alto risco' },
      risk_index: 90,
      abstention: [{ code: 'low_confidence', message: 'O modelo não teve segurança.' }],
    })
    expect(statusOf(normalizeAnalysis(raw))).toBe('analise_inconclusiva')
  })

  it('RF29: recusa versão de API que a interface não conhece', () => {
    const error = thrown(() => normalizeAnalysis(makeApiAnalysis({ api_version: 'v2' })))
    expect(error).toBeInstanceOf(AppError)
    expect(error.scenario).toBe('incompatible_api')
    const missing = thrown(() => normalizeAnalysis(makeApiAnalysis({ api_version: undefined })))
    expect(missing.scenario).toBe('incompatible_api')
  })

  it.each([
    ['corpo que não é objeto', 'texto'],
    ['sem id', makeApiAnalysis({ id: '' })],
    ['data inválida', makeApiAnalysis({ created_at: 'ontem' })],
    ['status desconhecido', makeApiAnalysis({ status: { code: 'verdadeira', label: 'Verdadeira' } })],
    ['status ausente', makeApiAnalysis({ status: null })],
    ['índice acima de 100', makeApiAnalysis({ risk_index: 101 })],
    ['índice negativo', makeApiAnalysis({ risk_index: -1 })],
    ['índice que não é número', makeApiAnalysis({ risk_index: '48' })],
  ])('recusa resposta incompatível: %s', (_name, raw) => {
    const error = thrown(() => normalizeAnalysis(raw))
    expect(error).toBeInstanceOf(AppError)
    expect(error.scenario).toBe('incompatible_api')
  })

  it('tolera campos técnicos ausentes, sem inventar valores', () => {
    const raw = makeApiAnalysis()
    delete raw.model
    delete raw.indicators
    delete raw.risk
    delete raw.versions
    delete raw.limitations
    const a = normalizeAnalysis(raw)
    expect(a.model.label).toBeNull()
    expect(a.model.confidence).toBeNull()
    expect(a.indicators.sensationalTerms).toEqual([])
    expect(a.risk.value).toBeNull()
    expect(a.limitations).toEqual([])
    expect(a.versions.model).toBe('')
  })

  it('o índice 0 e os limites 25 e 60 são lidos como números, não como ausentes', () => {
    for (const value of [0, 25, 60, 100]) {
      expect(normalizeAnalysis(makeApiAnalysis({ risk_index: value })).riskIndex).toBe(value)
    }
  })
})

describe('evidências (RF07, RF08)', () => {
  it('hoje a API manda "evidence.enabled=false" e nenhuma fonte', () => {
    const a = normalizeAnalysis(makeApiAnalysis())
    expect(a.evidence).toEqual({ status: 'disabled', enabled: false, sources: [] })
  })

  it('consulta habilitada sem fontes = evidências insuficientes', () => {
    const a = normalizeAnalysis(makeApiAnalysis({ evidence: { enabled: true, sources: [] } }))
    expect(a.evidence.status).toBe('none')
  })

  it('fonte com relação demonstrável é lida com todos os campos do RF08', () => {
    const a = normalizeAnalysis(
      makeApiAnalysis({
        evidence: {
          enabled: true,
          sources: [
            {
              relation: 'conflicting',
              publisher: 'Agência Exemplo',
              title: 'Checagem: linhas de ônibus seguem em operação',
              excerpt: 'A empresa informou que apenas três linhas terão horário alterado.',
              published_at: '2026-10-07',
              url: 'https://exemplo.org/checagem/123',
              relation_reason: 'O texto da fonte contradiz a paralisação total.',
            },
          ],
        },
      }),
    )
    expect(a.evidence.status).toBe('found')
    expect(a.evidence.sources[0]).toMatchObject({
      relation: 'conflicting',
      publisher: 'Agência Exemplo',
      excerpt: expect.stringMatching(/três linhas/),
      publishedAt: '2026-10-07',
      url: 'https://exemplo.org/checagem/123',
      reason: expect.stringMatching(/contradiz/),
    })
  })

  it('fonte sem relação demonstrável com a alegação não é exibida (RF08)', () => {
    expect(normalizeSource({ publisher: 'X', url: 'https://x.org' }, 0)).toBeNull()
    expect(normalizeSource({ relation: 'parecida', url: 'https://x.org' }, 0)).toBeNull()
    expect(normalizeSource(null, 0)).toBeNull()
  })

  it('campos ausentes da fonte ficam nulos ("não informado"), sem valores inventados', () => {
    const source = normalizeSource({ relation: 'contextual' }, 3)
    expect(source).toMatchObject({
      id: 'source-3',
      relation: 'contextual',
      publisher: null,
      title: null,
      excerpt: null,
      publishedAt: null,
      url: null,
    })
  })

  it('aceita os códigos de relação em português também', () => {
    expect(normalizeSource({ relation: 'compativel' }, 0)?.relation).toBe('compatible')
    expect(normalizeSource({ relation: 'INSUFICIENTE' }, 0)?.relation).toBe('insufficient')
  })

  it('evidence.failed marca falha na consulta de evidências, mesmo com fontes parciais', () => {
    expect(normalizeAnalysis(makeApiAnalysis({ evidence: { enabled: true, failed: true, sources: [] } })).evidence.status).toBe('failed')
    expect(normalizeAnalysis(makeApiAnalysis({ evidence: { enabled: true, error: { code: 'x' }, sources: [] } })).evidence.status).toBe('failed')
    expect(normalizeAnalysis(makeApiAnalysis({ evidence: { enabled: true, failed: true, sources: [{ relation: 'contextual' }] } })).evidence).toMatchObject({ status: 'failed', sources: [{ relation: 'contextual' }] })
  })
})

describe('safeHttpUrl (RNF16: conteúdo externo não confiável)', () => {
  it.each(['https://exemplo.org/a', 'http://exemplo.org/b?x=1'])('aceita %s', (url) => {
    expect(safeHttpUrl(url)).toBe(new URL(url).href)
  })

  it.each(['javascript:alert(1)', 'data:text/html;base64,AAAA', 'vbscript:x', '//exemplo.org', '/relativo', '', '   ', null, 42])(
    'rejeita %s',
    (url) => {
      expect(safeHttpUrl(url)).toBeNull()
    },
  )

  it('uma fonte com javascript: na URL perde o link, mas não quebra a leitura', () => {
    const source = normalizeSource({ relation: 'compatible', url: 'javascript:alert(1)' }, 0)
    expect(source?.url).toBeNull()
  })
})
