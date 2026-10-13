import { describe, expect, it } from 'vitest'
import { createConfig } from '../config.js'
import { formatNumber } from '../domain/format.js'
import { FEEDBACK_COMMENT_RETENTION_DAYS, HISTORY_MAX_ITEMS, TEXT_LIMITS, VISITOR_LIMIT } from '../domain/limits.js'
import { privacySections } from './privacy.js'

// RF30 (privacidade descreve o que o sistema faz) e RNF19 (o limite de visitante é explicado:
// finalidade, janela de 24 horas e limitações).

const CONFIGS = {
  'demonstração (padrão de hoje)': { accountsMode: 'demo', feedbackMode: 'demo', backend: { urlAnalysis: true, sources: true } },
  'contas e avaliação desligadas': { accountsMode: 'off', feedbackMode: 'off', backend: { urlAnalysis: true, sources: true } },
  'só contas desligadas': { accountsMode: 'off', feedbackMode: 'demo', backend: { urlAnalysis: true, sources: true } },
  'back end anterior': { accountsMode: 'demo', feedbackMode: 'demo', backend: { urlAnalysis: false, sources: false } },
  'modos reais (Etapa 4)': { accountsMode: 'real', feedbackMode: 'real', backend: { urlAnalysis: true, sources: true } },
}

const textOf = (section) => section.blocks.map((block) => (block.type === 'p' ? block.text : block.items.join('\n'))).join('\n')
const allText = (config) => privacySections(config).map((section) => `${section.title}\n${textOf(section)}`).join('\n\n')
const byId = (config, id) => privacySections(config).find((section) => section.id === id)

describe('estrutura', () => {
  it.each(Object.entries(CONFIGS))('%s: seções bem formadas, com identificadores únicos', (_name, config) => {
    const sections = privacySections(config)
    const ids = sections.map((section) => section.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const section of sections) {
      expect(section.title.length).toBeGreaterThan(5)
      expect(section.blocks.length).toBeGreaterThan(0)
      for (const block of section.blocks) {
        if (block.type === 'p') {
          expect(block.text).toBe(block.text.trim())
          expect(block.text.length).toBeGreaterThan(15)
          expect(block.text).not.toMatch(/ {2,}/)
        } else {
          expect(block.items.length).toBeGreaterThan(0)
          expect(block.items.every((item) => item === item.trim() && item.length > 10)).toBe(true)
        }
      }
    }
  })

  it('cobre os assuntos do RF30, nesta ordem de leitura, e termina com as pendências', () => {
    const ids = privacySections(CONFIGS['demonstração (padrão de hoje)']).map((s) => s.id)
    expect(ids).toEqual(['conteudo', 'visitante', 'historico', 'contas', 'feedback', 'controles', 'demonstracao', 'pendencias'])
  })

  it('a seção de demonstração só existe quando algo é demonstração', () => {
    expect(byId(CONFIGS['demonstração (padrão de hoje)'], 'demonstracao')).toBeDefined()
    expect(byId(CONFIGS['só contas desligadas'], 'demonstracao')).toBeDefined()
    expect(byId(CONFIGS['contas e avaliação desligadas'], 'demonstracao')).toBeUndefined()
    expect(byId(CONFIGS['modos reais (Etapa 4)'], 'demonstracao')).toBeUndefined()
  })

  it('é a seção "demonstracao" que o aviso do topo da página aponta (/privacidade#demonstracao)', () => {
    expect(byId(CONFIGS['demonstração (padrão de hoje)'], 'demonstracao').title).toBe('O que é demonstração nesta versão')
  })
})

describe('RNF19: limite de visitante', () => {
  const visitor = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'visitante'))

  it('informa a janela de 24 horas, o número de análises e que texto e link usam o mesmo contador', () => {
    expect(visitor).toContain(`até ${VISITOR_LIMIT.max} análises em uma janela de 24 horas`)
    expect(visitor).toMatch(/começa na primeira análise concluída/)
    expect(visitor).toMatch(/Texto e link usam o mesmo contador/)
  })

  it('informa a finalidade do controle', () => {
    expect(visitor).toMatch(/O limite existe para controlar o uso sem conta/)
  })

  it('informa as limitações do controle e que não usa impressão digital do aparelho', () => {
    expect(visitor).toMatch(/limitações/)
    expect(visitor).toMatch(/limpar os dados do navegador/)
    expect(visitor).toMatch(/não usa impressão digital do aparelho/i)
  })

  it('RF33: diz o que conta e o que não conta para o limite', () => {
    expect(visitor).toMatch(/resultado ou com análise inconclusiva/)
    expect(visitor).toMatch(/Textos recusados e falhas do sistema não gastam o limite/)
  })

  it('com contas, oferece entrar ou criar conta; sem contas, não promete isso', () => {
    expect(visitor).toMatch(/oferece entrar ou criar uma conta/)
    const off = textOf(byId(CONFIGS['contas e avaliação desligadas'], 'visitante'))
    expect(off).not.toMatch(/criar uma conta/)
    expect(off).toMatch(/quando o uso como visitante será liberado de novo/)
  })
})

describe('RF05 e RF30: o conteúdo enviado', () => {
  it('diz que o texto não é guardado e o que o servidor guarda no lugar', () => {
    const text = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'conteudo'))
    expect(text).toContain(`de ${TEXT_LIMITS.min} a ${formatNumber(TEXT_LIMITS.max)} caracteres`)
    expect(text).toMatch(/O servidor não guarda o texto/)
    expect(text).toMatch(/resumo curto da alegação/)
    expect(text).toMatch(/até 140 caracteres/)
    expect(text).toMatch(/e-mails, CPFs e telefones mascarados/)
    expect(text).toMatch(/identificador anônimo do seu navegador/)
  })

  it('avisa que o endereço do resultado pode ser aberto por quem o tiver', () => {
    expect(textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'conteudo'))).toMatch(/Quem tiver o endereço de um resultado/)
  })

  it('não inventa o prazo de guarda: diz que ainda não foi definido', () => {
    const config = CONFIGS['demonstração (padrão de hoje)']
    expect(textOf(byId(config, 'conteudo'))).toMatch(/ainda não foi definido pela equipe/)
    expect(textOf(byId(config, 'pendencias'))).toMatch(/por quanto tempo os registros técnicos das análises ficam guardados/)
    expect(allText(config)).not.toMatch(/\b\d+ (dias|meses|anos)\b/)
  })

  it('hoje, descreve busca e possível síntese externa; com API anterior, não afirma esses envios', () => {
    const current = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'conteudo'))
    expect(current).toMatch(/envia palavras do título ou da alegação a serviços de busca/)
    expect(current).toMatch(/até 1\.200 caracteres do corpo/)
    expect(current).toMatch(/campos derivados podem repetir trechos/)
    expect(textOf(byId(CONFIGS['back end anterior'], 'conteudo'))).toMatch(/Ele não é enviado a outros serviços/)
  })

  it('hoje não descreve link como indisponível; com API anterior, explica a limitação', () => {
    expect(textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'conteudo'))).not.toMatch(/análise por link ainda não está disponível/)
    expect(textOf(byId(CONFIGS['back end anterior'], 'conteudo'))).toMatch(/A análise por link ainda não está disponível/)
  })
})

describe('histórico (RF20)', () => {
  it('descreve o que é guardado, o teto e os controles, e que o servidor não é afetado', () => {
    const text = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'historico'))
    expect(text).toMatch(/O texto completo nunca entra no histórico/)
    expect(text).toContain(`até ${HISTORY_MAX_ITEMS} itens`)
    expect(text).toMatch(/desligar o histórico, excluir um item ou limpar tudo/)
    expect(text).toMatch(/não é apagado por isso/)
  })
})

describe('contas (RF31, RF32, RF34)', () => {
  it('em demonstração: diz que é simulação, que nada é guardado e que não há sincronização', () => {
    const text = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'contas'))
    expect(text).toMatch(/são uma simulação/)
    expect(text).toMatch(/não são guardados nem enviados/)
    expect(text).toMatch(/Não existe sincronização entre aparelhos/)
  })

  it('desligadas: diz que não há contas', () => {
    expect(textOf(byId(CONFIGS['contas e avaliação desligadas'], 'contas'))).toMatch(/Esta versão não tem contas/)
  })

  it('reais: o histórico só é vinculado com confirmação e a exclusão é descrita', () => {
    const text = textOf(byId(CONFIGS['modos reais (Etapa 4)'], 'contas'))
    expect(text).toMatch(/só é vinculado à conta se você confirmar/)
    expect(text).toMatch(/pode excluir a conta/)
  })

  it('os controles listam "Minha conta" só quando há contas', () => {
    expect(textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'controles'))).toMatch(/Minha conta/)
    expect(textOf(byId(CONFIGS['contas e avaliação desligadas'], 'controles'))).not.toMatch(/Minha conta/)
  })
})

describe('avaliação da análise (RF19, RNF10)', () => {
  it('em demonstração: nada é enviado nem guardado, e não cita prazo de guarda', () => {
    const text = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'feedback'))
    expect(text).toMatch(/não são enviados nem guardados/)
    expect(text).not.toContain(`${FEEDBACK_COMMENT_RETENTION_DAYS} dias`)
  })

  it('real: informa a finalidade, que não vira rótulo de treino, o prazo do RNF10 e que o texto não vai junto', () => {
    const text = textOf(byId(CONFIGS['modos reais (Etapa 4)'], 'feedback'))
    expect(text).toMatch(/não é usada como rótulo para treinar o modelo/)
    expect(text).toContain(`até ${FEEDBACK_COMMENT_RETENTION_DAYS} dias`)
    expect(text).toMatch(/O texto analisado não é enviado junto/)
  })

  it('desligada: diz que não coleta', () => {
    expect(textOf(byId(CONFIGS['contas e avaliação desligadas'], 'feedback'))).toMatch(/não coleta avaliações/)
  })
})

describe('pendências (honestidade)', () => {
  it('lista o que a equipe ainda precisa definir, incluindo a revisão jurídica', () => {
    const text = textOf(byId(CONFIGS['demonstração (padrão de hoje)'], 'pendencias'))
    expect(text).toMatch(/base legal/)
    expect(text).toMatch(/canal para você tirar dúvidas/)
    expect(text).toMatch(/revisão jurídica/)
  })
})

describe('o que o texto nunca pode dizer', () => {
  it.each(Object.entries(CONFIGS))('%s: sem promessas que o código não cumpre', (_name, config) => {
    const text = allText(config)
    expect(text).not.toMatch(/Fake Eyes/i)
    expect(text).not.toMatch(/criptograf|encripta|criptografad/i)
    expect(text).not.toMatch(/100\s?%/)
    expect(text).not.toMatch(/garant(imos|ia|e|ido)\b/i)
    expect(text).not.toMatch(/em conformidade com a LGPD|totalmente seguro|nunca será compartilhad|não compartilhamos com ningu/i)
    expect(text).not.toMatch(/Google|Gemini|OpenAI|Meta\b|Twilio/i)
    expect(text).not.toMatch(/cookies? (de|para) (anúncios|publicidade|rastreamento)/i)
  })

  it('não promete apagar o que fica no servidor', () => {
    const text = allText(CONFIGS['demonstração (padrão de hoje)'])
    expect(text).not.toMatch(/apagamos (tudo|seus dados)/i)
    expect(text).not.toMatch(/exclu[ií]mos do servidor/i)
  })
})

describe('configuração real da aplicação', () => {
  it('createConfig produz uma configuração aceita pelo conteúdo', () => {
    const sections = privacySections(createConfig({}))
    expect(sections.map((s) => s.id)).toContain('pendencias')
  })
})
