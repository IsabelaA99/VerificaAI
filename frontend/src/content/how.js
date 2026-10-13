// @ts-check
// Conteúdo da página "Como funciona" (RF30): finalidade, funcionamento geral, significado do
// índice de risco, uso de fontes e limitações.
//
// Regra do RF30: o texto precisa corresponder ao que o sistema FAZ, e não pode sugerir verificação
// humana. Por isso as frases que dependem do back end (análise por link, consulta a fontes) mudam
// conforme config.backend, e o teste de conteúdo (how.test.js) confere o que for proibido dizer.

import { RISK_BANDS } from '../domain/status.js'
import { TEXT_LIMITS, VISITOR_LIMIT } from '../domain/limits.js'
import { formatNumber } from '../domain/format.js'

/**
 * @typedef {{ type: 'p', text: string } | { type: 'ul', items: string[] }} Block
 * @typedef {{ id: string, title: string, blocks: Block[] }} Section
 */

/** @param {string} text @returns {Block} */
const p = (text) => ({ type: 'p', text })
/** @param {string[]} items @returns {Block} */
const ul = (items) => ({ type: 'ul', items })

/** Faixa do índice escrita por extenso, a partir das constantes do RF16. */
export const BAND_RANGES = Object.freeze({
  poucos_sinais_de_risco: `0 a ${RISK_BANDS.lowMax}`,
  requer_atencao: `acima de ${RISK_BANDS.lowMax} até ${RISK_BANDS.attentionMax}`,
  alto_risco: `acima de ${RISK_BANDS.attentionMax} até ${RISK_BANDS.max}`,
  analise_inconclusiva: 'sem índice',
})

/**
 * As quatro passagens do método, em linguagem simples.
 * @param {{ backend: { urlAnalysis: boolean, sources: boolean } }} config
 * @returns {{ title: string, text: string }[]}
 */
export function howSteps({ backend }) {
  return [
    {
      title: 'Você envia o conteúdo',
      text:
        `Cole o texto da notícia ou da mensagem, com ${formatNumber(TEXT_LIMITS.min)} a ${formatNumber(TEXT_LIMITS.max)} caracteres. ` +
        (backend.urlAnalysis
          ? 'Você também pode enviar o endereço (link) da notícia. '
          : 'O envio por link ainda não está disponível: por enquanto, cole o texto. ') +
        'Só a opção que você escolheu é enviada.',
    },
    {
      title: 'O sistema procura sinais',
      text:
        'Um modelo de inteligência artificial treinado com textos em português estima o quanto o texto se parece com notícias falsas que ele viu no treinamento. ' +
        'Regras simples também procuram sinais de linguagem apelativa, como palavras em caixa alta e exclamações repetidas. ' +
        'Esses sinais ajudam a olhar com mais cuidado, mas nenhum deles prova sozinho que algo é falso.',
    },
    {
      title: 'As fontes são consultadas',
      text: backend.sources
        ? 'O sistema busca checagens relacionadas à alegação e classifica os resultados como compatíveis, conflitantes ou contextuais com base no veredito ou no título encontrado. Essa classificação automática pode errar; confira a fonte antes de usá-la como evidência.'
        : 'A consulta a fontes externas ainda não está habilitada nesta versão. Quando estiver, cada fonte aparecerá separada da estimativa do modelo, dizendo se é compatível, conflitante, contextual ou insuficiente.',
    },
    {
      title: 'Você recebe uma explicação',
      text: 'O resultado mostra a categoria, o índice de risco, os fatores principais, as fontes (quando houver), as limitações e o que fazer em seguida. Se a confiança do modelo for baixa ou os trechos divergirem muito, a análise fica inconclusiva.',
    },
  ]
}

/**
 * Seções de texto corrido da página, na ordem de leitura.
 * @param {{ backend: { urlAnalysis: boolean, sources: boolean } }} config
 * @returns {Section[]}
 */
export function howSections({ backend }) {
  return [
    {
      id: 'finalidade',
      title: 'Para que serve o Apura',
      blocks: [
        p('O Apura é um apoio à leitura crítica de textos em português. Ele mostra sinais de risco de desinformação, explica o que encontrou e sugere o que fazer antes de compartilhar.'),
        p('Ele não decide o que é verdade. A análise é feita por computador e nenhuma pessoa revisa o resultado. A decisão de acreditar ou compartilhar continua sendo sua.'),
      ],
    },
    {
      id: 'indice',
      title: 'O que significa o índice de risco',
      blocks: [
        p(`O índice vai de 0 a ${RISK_BANDS.max}. Ele é um indicador de risco de desinformação. Ele não é a probabilidade de a notícia ser falsa e não é uma certeza.`),
        p(
          'Como ele é calculado: o sistema soma sinais normalizados (a estimativa do modelo, os indicadores de linguagem e, quando houver, o conflito entre fontes), cada um com um peso fixo definido numa versão registrada das regras. Sinais que faltam são ignorados. Cada resultado mostra a versão das regras usada, e as faixas e os pesos podem mudar em versões futuras.',
        ),
        p('Quando a análise é inconclusiva, ela tem prioridade sobre qualquer faixa: não há índice, e isso não quer dizer que a notícia seja verdadeira nem falsa.'),
      ],
    },
    {
      id: 'inconclusiva',
      title: 'Quando a análise fica inconclusiva',
      blocks: [
        p('O Apura marca a análise como inconclusiva quando:'),
        ul([
          'a confiança calculada pelo modelo fica abaixo do limite definido nas regras;',
          'os trechos analisados apresentam previsões muito diferentes entre si.',
        ]),
        p('A ausência de fontes externas, por si só, não torna a análise inconclusiva nesta versão.'),
        p('Cada resultado inconclusivo mostra o motivo, com uma mensagem própria.'),
      ],
    },
    {
      id: 'fontes',
      title: 'Como as fontes são usadas',
      blocks: backend.sources
        ? [
            p('O Apura pesquisa checagens em um serviço especializado quando configurado. Se ele não trouxer resultados, tenta uma busca pública na internet.'),
            p('A relação compatível, conflitante ou contextual é atribuída automaticamente pelo veredito da checagem ou por palavras do título e do resumo. A correspondência com a alegação ainda não é verificada em profundidade; uma fonte sem relação direta pode aparecer e influenciar o índice. Confira o link original.'),
            p('Se a busca não retornar fontes, o resultado mostra essa ausência. Isso não prova nem refuta a alegação.'),
          ]
        : [
            p('Nesta versão, o Apura ainda não consulta fontes externas. Nenhuma evidência externa é verificada: o resultado vem só do texto enviado.'),
            p('Quando a consulta for habilitada, cada fonte aparecerá num cartão com o veículo ou a instituição, a data, o trecho usado, o link e o motivo de ela estar ali, e será classificada como compatível, conflitante, contextual ou insuficiente, sempre separada da estimativa do modelo.'),
            p('Em cada resultado, a seção “Fontes consultadas” diz o que aconteceu com as fontes naquela análise. O Apura não inventa referências para preencher a resposta.'),
          ],
    },
    {
      id: 'limitacoes',
      title: 'O que o Apura não faz',
      blocks: [
        ul([
          'Não há verificação humana: a análise é feita por computador, e ninguém revisa o seu resultado.',
          'O resultado não substitui a checagem em fontes confiáveis. Procure sempre a fonte original.',
          'O modelo pode errar. Conteúdo muito recente, assuntos locais, falta de fonte ou evidências conflitantes dificultam uma conclusão responsável.',
          'O estilo de escrita, sozinho, não prova que algo é falso ou verdadeiro. Um texto verdadeiro pode ser sensacionalista, e um falso pode parecer formal.',
          'A ausência de evidência não comprova falsidade.',
          `Só analisa textos em português, com ${formatNumber(TEXT_LIMITS.min)} a ${formatNumber(TEXT_LIMITS.max)} caracteres. Quando só uma parte do texto é analisada, a tela avisa.`,
        ]),
      ],
    },
  ]
}

/**
 * Perguntas frequentes.
 * @param {{ accountsMode: 'demo' | 'off' }} config
 * @returns {{ question: string, answer: string }[]}
 */
export function howFaq({ accountsMode }) {
  return [
    {
      question: 'O índice é uma porcentagem de falsidade?',
      answer: `Não. É um indicador de risco de 0 a ${RISK_BANDS.max}, calculado por regras versionadas. Ele ajuda a decidir se vale desconfiar e pesquisar mais, mas não diz a chance de a notícia ser falsa.`,
    },
    {
      question: 'Alguém revisa o meu resultado?',
      answer: 'Não. A análise é feita por computador, do começo ao fim. Por isso o Apura sempre recomenda conferir a fonte original antes de compartilhar.',
    },
    {
      question: 'Por que o resultado pode ser inconclusivo?',
      answer: 'Porque a confiança calculada pelo modelo pode ficar abaixo do limite das regras ou os trechos do texto podem produzir previsões muito diferentes. O resultado mostra o motivo. A falta de fontes externas, sozinha, não gera esse status nesta versão.',
    },
    {
      question: 'Preciso criar uma conta?',
      answer:
        `Não para começar. Sem conta, cada navegador pode fazer até ${VISITOR_LIMIT.max} análises em 24 horas, contadas a partir da primeira.` +
        (accountsMode === 'off'
          ? ' Passado o limite, é preciso esperar a renovação.'
          : ' Passado o limite, você pode entrar ou criar uma conta para continuar, ou esperar a renovação.'),
    },
    {
      question: 'O Apura guarda o texto que eu enviei?',
      answer: 'Não como texto integral em um campo da análise. O servidor guarda um resumo curto da alegação, o resultado, dados técnicos e versões; explicações e fontes podem repetir trechos do conteúdo. A página de Privacidade explica o que é guardado e onde.',
    },
  ]
}
