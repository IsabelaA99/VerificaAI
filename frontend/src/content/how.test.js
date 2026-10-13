import { describe, expect, it } from 'vitest'
import { createConfig } from '../config.js'
import { formatNumber } from '../domain/format.js'
import { TEXT_LIMITS, VISITOR_LIMIT } from '../domain/limits.js'
import { RISK_BANDS, STATUS_CODES } from '../domain/status.js'
import { BAND_RANGES, howFaq, howSections, howSteps } from './how.js'

// RF30: o texto de "Como funciona" tem de corresponder ao que o sistema FAZ — sem sugerir verificação
// humana, sem prometer o que não existe e sem apresentar o índice como probabilidade.

const BACKENDS = [
  ['API anterior (sem link e sem fontes)', { urlAnalysis: false, sources: false }],
  ['com análise por link', { urlAnalysis: true, sources: false }],
  ['com fontes', { urlAnalysis: false, sources: true }],
  ['completo', { urlAnalysis: true, sources: true }],
]

/** Todo o texto de uma configuração, numa só string, para procurar frases proibidas. */
function allText(backend, accountsMode = 'demo') {
  const parts = []
  for (const step of howSteps({ backend })) parts.push(step.title, step.text)
  for (const section of howSections({ backend })) {
    parts.push(section.title)
    for (const block of section.blocks) parts.push(...(block.type === 'p' ? [block.text] : block.items))
  }
  for (const item of howFaq({ accountsMode })) parts.push(item.question, item.answer)
  return parts.join('\n')
}

describe('estrutura', () => {
  it.each(BACKENDS)('%s: seções na ordem do RF30, todas com título e texto', (_name, backend) => {
    const sections = howSections({ backend })
    expect(sections.map((s) => s.id)).toEqual(['finalidade', 'indice', 'inconclusiva', 'fontes', 'limitacoes'])
    for (const section of sections) {
      expect(section.title.length).toBeGreaterThan(5)
      expect(section.blocks.length).toBeGreaterThan(0)
      for (const block of section.blocks) {
        if (block.type === 'p') expect(block.text.trim().length).toBeGreaterThan(20)
        else expect(block.items.every((item) => item.trim().length > 10)).toBe(true)
      }
    }
  })

  it('os identificadores de seção não se repetem (são âncoras da página)', () => {
    const ids = howSections({ backend: BACKENDS[0][1] }).map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('há quatro passos do método, em ordem', () => {
    const steps = howSteps({ backend: BACKENDS[0][1] })
    expect(steps.map((s) => s.title)).toEqual([
      'Você envia o conteúdo',
      'O sistema procura sinais',
      'As fontes são consultadas',
      'Você recebe uma explicação',
    ])
  })
})

describe('RF16: o índice e as faixas', () => {
  it('as faixas escritas vêm das mesmas constantes que desenham a escala', () => {
    expect(BAND_RANGES).toEqual({
      poucos_sinais_de_risco: `0 a ${RISK_BANDS.lowMax}`,
      requer_atencao: `acima de ${RISK_BANDS.lowMax} até ${RISK_BANDS.attentionMax}`,
      alto_risco: `acima de ${RISK_BANDS.attentionMax} até ${RISK_BANDS.max}`,
      analise_inconclusiva: 'sem índice',
    })
    expect(Object.keys(BAND_RANGES).sort()).toEqual([...STATUS_CODES].sort())
    expect(BAND_RANGES.poucos_sinais_de_risco).toBe('0 a 25')
    expect(BAND_RANGES.requer_atencao).toBe('acima de 25 até 60')
    expect(BAND_RANGES.alto_risco).toBe('acima de 60 até 100')
  })

  it('o texto do índice diz que não é probabilidade nem certeza e que inconclusiva tem prioridade', () => {
    const text = howSections({ backend: BACKENDS[0][1] }).find((s) => s.id === 'indice').blocks.map((b) => b.text).join(' ')
    expect(text).toContain('de 0 a 100')
    expect(text).toMatch(/não é a probabilidade de a notícia ser falsa e não é uma certeza/)
    expect(text).toMatch(/inconclusiva, ela tem prioridade sobre qualquer faixa/)
    expect(text).toMatch(/versão das regras/)
  })
})

describe('RF30: o que o texto afirma depende do que o back end faz', () => {
  it('com uma API anterior: descreve os recursos ausentes', () => {
    const text = allText(BACKENDS[0][1])
    expect(text).toMatch(/O envio por link ainda não está disponível/)
    expect(text).toMatch(/consulta a fontes externas ainda não está habilitada/)
    expect(text).toMatch(/ainda não consulta fontes externas/)
    expect(text).toMatch(/Nenhuma evidência externa é verificada/)
  })

  it('com o link no ar: deixa de dizer que ele não existe', () => {
    const text = allText({ urlAnalysis: true, sources: false })
    expect(text).toMatch(/Você também pode enviar o endereço \(link\) da notícia/)
    expect(text).not.toMatch(/envio por link ainda não está disponível/)
  })

  it('com as fontes no ar: descreve a consulta e deixa de dizer que ela não existe', () => {
    const text = allText({ urlAnalysis: false, sources: true })
    expect(text).toMatch(/busca checagens relacionadas à alegação/)
    expect(text).not.toMatch(/ainda não consulta fontes externas/)
    expect(text).not.toMatch(/consulta a fontes externas ainda não está habilitada/)
  })

  it('o padrão atual descreve link e fontes sem prometer validação da relação com a alegação', () => {
    const text = allText(createConfig({}).backend)
    expect(text).toMatch(/Você também pode enviar o endereço \(link\) da notícia/)
    expect(text).toMatch(/tenta uma busca pública na internet/)
    expect(text).toMatch(/uma fonte sem relação direta pode aparecer e influenciar o índice/)
    expect(text).not.toMatch(/ainda não consulta fontes externas|envio por link ainda não está disponível/)
  })
})

describe('RF30: o que o texto nunca pode dizer', () => {
  it.each(BACKENDS)('%s: não sugere verificação humana', (_name, backend) => {
    const text = allText(backend)
    const claims = [
      /verificad[oa]s? por (especialistas|humanos|pessoas|jornalistas|checadores|nossa equipe|uma equipe)/i,
      /revisad[oa]s? por (uma )?(pessoa|humano|especialista|equipe|jornalista)/i,
      /(nossa|uma) equipe (de )?(checadores|jornalistas|especialistas|editores)/i,
      /checadores (profissionais|humanos)/i,
      /(especialistas|jornalistas|editores) (revisam|verificam|checam|conferem)/i,
    ]
    for (const claim of claims) expect(text).not.toMatch(claim)
  })

  it.each(BACKENDS)('%s: toda menção a "verificação humana" é para negá-la', (_name, backend) => {
    const text = allText(backend)
    for (const match of text.matchAll(/verifica(ç|c)(ão|ao) humana/gi)) {
      const before = text.slice(Math.max(0, match.index - 14), match.index).toLowerCase()
      expect(before, `trecho: …${text.slice(Math.max(0, match.index - 30), match.index + 30)}…`).toMatch(/n(ã|a)o h(á|a) $/)
    }
  })

  it.each(BACKENDS)('%s: não promete certeza, garantia nem número de acerto', (_name, backend) => {
    const text = allText(backend)
    expect(text).not.toMatch(/garant(imos|ia|e|ido)\b/i)
    expect(text).not.toMatch(/infal[ií]vel/i)
    expect(text).not.toMatch(/100\s?%/)
    expect(text).not.toMatch(/acur[áa]cia|precis[ãa]o de \d|taxa de acerto|acerta \d/i)
    expect(text).not.toMatch(/\bsempre (acerta|certo|verdade)/i)
  })

  it.each(BACKENDS)('%s: nunca chama o índice de "probabilidade de ser falsa" sem negar', (_name, backend) => {
    const text = allText(backend)
    for (const match of text.matchAll(/probabilidade de (a notícia )?ser falsa/gi)) {
      const before = text.slice(Math.max(0, match.index - 20), match.index).toLowerCase()
      expect(before, `trecho: …${text.slice(Math.max(0, match.index - 40), match.index + 40)}…`).toMatch(/n(ã|a)o é a $/)
    }
  })

  it.each(BACKENDS)('%s: usa o nome Apura, nunca o nome antigo', (_name, backend) => {
    expect(allText(backend)).not.toMatch(/Fake Eyes/i)
  })

  it.each(BACKENDS)('%s: não cita serviços externos que o back end não usa hoje', (_name, backend) => {
    const text = allText(backend)
    expect(text).not.toMatch(/Gemini|OpenAI|ChatGPT|Fact Check Tools|Google Fact/i)
  })
})

describe('limites do conteúdo vêm das constantes', () => {
  it('o tamanho do texto aceito é o do RF01', () => {
    const text = allText(BACKENDS[0][1])
    expect(text).toContain(`${TEXT_LIMITS.min} a ${formatNumber(TEXT_LIMITS.max)} caracteres`)
  })

  it('o limite de visitante é o do RF33', () => {
    const faq = howFaq({ accountsMode: 'demo' }).find((item) => item.question === 'Preciso criar uma conta?')
    expect(faq.answer).toContain(`até ${VISITOR_LIMIT.max} análises em 24 horas`)
  })
})

describe('perguntas frequentes', () => {
  it('são cinco, cada uma com pergunta e resposta', () => {
    const faq = howFaq({ accountsMode: 'demo' })
    expect(faq).toHaveLength(5)
    for (const item of faq) {
      expect(item.question.endsWith('?')).toBe(true)
      expect(item.answer.length).toBeGreaterThan(40)
    }
  })

  it('com contas ligadas, oferece entrar ou criar conta depois do limite; desligadas, só esperar', () => {
    const find = (mode) => howFaq({ accountsMode: mode }).find((item) => item.question === 'Preciso criar uma conta?').answer
    expect(find('demo')).toMatch(/entrar ou criar uma conta/)
    expect(find('off')).not.toMatch(/criar uma conta para continuar|entrar ou criar/)
    expect(find('off')).toMatch(/esperar a renovação/)
  })

  it('a resposta sobre o texto enviado distingue o conteúdo integral dos dados derivados', () => {
    const answer = howFaq({ accountsMode: 'demo' }).find((item) => item.question === 'O Apura guarda o texto que eu enviei?').answer
    expect(answer).toMatch(/^Não como texto integral/)
    expect(answer).toMatch(/resumo curto da alegação/)
  })
})
