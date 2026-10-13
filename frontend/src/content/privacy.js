// @ts-check
// Conteúdo da página "Privacidade" (RF30): armazenamento local, contas, histórico sincronizado,
// limite de visitante e tratamento de feedback.
//
// O texto descreve o que o sistema FAZ hoje. A origem de cada afirmação:
//   - back end: models.Analysis, preprocessing.summarize_claim e mask_pii,
//     pipeline.py, factcheck.py e llm.py;
//   - esta interface: src/services (storage, historyStore, visitorLimitStore, gateways).
// Onde a equipe ainda não decidiu algo (prazo de guarda, base legal, canal de atendimento), o texto
// diz que está por definir, em vez de inventar. Tudo isso precisa de revisão jurídica antes de
// virar política final.
//
// As seções de contas e de feedback mudam conforme o modo configurado (demo, off). Quando os
// endpoints reais existirem (Etapa 4), as frases "reais" abaixo devem ser conferidas contra o
// que o back end de fato faz.

import { FEEDBACK_COMMENT_RETENTION_DAYS, HISTORY_MAX_ITEMS, TEXT_LIMITS, VISITOR_LIMIT } from '../domain/limits.js'
import { formatNumber } from '../domain/format.js'

/**
 * @typedef {{ type: 'p', text: string } | { type: 'ul', items: string[] }} Block
 * @typedef {{ id: string, title: string, blocks: Block[] }} Section
 * @typedef {{
 *   accountsMode: 'demo' | 'off',
 *   feedbackMode: 'demo' | 'off',
 *   backend: { urlAnalysis: boolean, sources: boolean },
 * }} PrivacyConfig
 */

/** @param {string} text @returns {Block} */
const p = (text) => ({ type: 'p', text })
/** @param {string[]} items @returns {Block} */
const ul = (items) => ({ type: 'ul', items })

/** @param {PrivacyConfig} config @returns {Section} */
function contentSection({ backend }) {
  return {
    id: 'conteudo',
    title: 'O conteúdo que você envia',
    blocks: [
      p(
        `O texto que você cola (de ${formatNumber(TEXT_LIMITS.min)} a ${formatNumber(TEXT_LIMITS.max)} caracteres) é enviado ao servidor do Apura para ser analisado. O servidor não guarda o texto integral como campo da análise, mas guarda o resultado e alguns dados derivados dele.`,
      ),
      backend.sources
        ? p('Para procurar checagens, o servidor envia palavras do título ou da alegação a serviços de busca. Se uma chave de IA externa estiver configurada, também pode enviar o título, até 1.200 caracteres do corpo e resumos das fontes para gerar a explicação. Sem essa chave, usa uma síntese local.')
        : p('Nesta versão, o texto é analisado dentro do próprio servidor do Apura. Ele não é enviado a outros serviços.'),
      p('O que o servidor guarda de cada análise:'),
      ul([
        'um resumo curto da alegação (o título ou a primeira frase, com até 140 caracteres), com e-mails, CPFs e telefones mascarados;',
        'o resultado: categoria, índice de risco, explicações, fontes e limitações; esses campos derivados podem repetir trechos do conteúdo enviado ou encontrado;',
        'as versões do modelo e das regras usadas, a data e a duração da análise;',
        'um identificador anônimo do seu navegador, criado ao acessar o site.',
      ]),
      p('Quem tiver o endereço de um resultado (o link que começa com /resultado/) consegue abrir o resumo daquela análise, que não inclui o texto enviado. Não compartilhe o endereço se não quiser que outra pessoa o veja.'),
      ...(backend.urlAnalysis
        ? []
        : [p('A análise por link ainda não está disponível. Se você tentar enviar um endereço, ele chega ao servidor, que responde que essa função ainda não existe; nada é analisado nem guardado.')]),
      p('Por quanto tempo o servidor guarda esses registros ainda não foi definido pela equipe.'),
      p('Não envie informações pessoais ou sigilosas.'),
    ],
  }
}

/** @param {PrivacyConfig} config @returns {Section} */
function visitorSection({ accountsMode }) {
  return {
    id: 'visitante',
    title: 'Uso sem conta e limite de visitante',
    blocks: [
      p(
        `Você pode usar o Apura sem conta. Cada navegador faz até ${VISITOR_LIMIT.max} análises em uma janela de 24 horas, que começa na primeira análise concluída. Texto e link usam o mesmo contador.`,
      ),
      // RNF19: a política precisa dizer a finalidade, a janela de 24 horas e as limitações do controle.
      p(
        accountsMode === 'off'
          ? 'O limite existe para controlar o uso sem conta. Depois dele, a tela informa quando o uso como visitante será liberado de novo.'
          : 'O limite existe para controlar o uso sem conta. Depois dele, a tela oferece entrar ou criar uma conta e informa quando o uso como visitante será liberado de novo.',
      ),
      p('Só contam para o limite as análises que terminam com resultado ou com análise inconclusiva. Textos recusados e falhas do sistema não gastam o limite.'),
      p(
        'Para isso, o navegador guarda a hora da primeira análise e quantas já foram feitas. Esse controle tem limitações: nesta versão, a contagem é feita só neste navegador, então, se você limpar os dados do navegador ou usar outro navegador, ela recomeça. O Apura não usa impressão digital do aparelho para tentar reconhecer você.',
      ),
    ],
  }
}

/** @returns {Section} */
function historySection() {
  return {
    id: 'historico',
    title: 'Histórico neste navegador',
    blocks: [
      p('O histórico é opcional e fica só neste navegador. Cada item guarda o resumo da alegação, a categoria do resultado, a data e o código da análise. O texto completo nunca entra no histórico.'),
      p(`Ele guarda até ${HISTORY_MAX_ITEMS} itens; os mais antigos saem para dar lugar aos novos. Você pode desligar o histórico, excluir um item ou limpar tudo, em “Meu histórico”. Limpar os dados do navegador também apaga o histórico.`),
      p('Excluir o histórico apaga a lista deste navegador. O registro técnico de cada análise no servidor (descrito acima) não é apagado por isso.'),
    ],
  }
}

/** @param {PrivacyConfig} config @returns {Section} */
function accountsSection({ accountsMode }) {
  if (accountsMode === 'off') {
    return {
      id: 'contas',
      title: 'Contas e histórico sincronizado',
      blocks: [p('Esta versão não tem contas. Por isso não há histórico sincronizado entre aparelhos: o histórico fica só neste navegador.')],
    }
  }
  if (accountsMode === 'demo') {
    return {
      id: 'contas',
      title: 'Contas e histórico sincronizado',
      blocks: [
        p('Nesta versão, entrar e criar conta são uma simulação. O e-mail e a senha que você digita não são guardados nem enviados. O navegador só lembra que você “entrou” e se escolheu vincular o histórico.'),
        p('Não existe sincronização entre aparelhos: o histórico continua só neste navegador, mesmo com a conta de demonstração. Quem “entra” deixa de ter o limite de visitante apenas neste navegador.'),
        p('Quando as contas forem reais, o cadastro pedirá só o que for necessário, o histórico deste navegador só será vinculado se você confirmar, e você poderá excluir a conta e os dados associados.'),
      ],
    }
  }
  return {
    id: 'contas',
    title: 'Contas e histórico sincronizado',
    blocks: [
      p('Com uma conta, as novas análises ficam ligadas a você e aparecem nos seus aparelhos. O histórico deste navegador só é vinculado à conta se você confirmar.'),
      p('Você pode sair a qualquer momento e pode excluir a conta: o acesso é encerrado e os dados da conta e o histórico ligado a ela deixam de estar disponíveis. Registros que a lei obrigue a manter ficam separados, reduzidos ao mínimo e com prazo definido.'),
    ],
  }
}

/** @param {PrivacyConfig} config @returns {Section} */
function feedbackSection({ feedbackMode }) {
  if (feedbackMode === 'off') {
    return {
      id: 'feedback',
      title: 'Avaliações da análise',
      blocks: [p('Esta versão não coleta avaliações da análise.')],
    }
  }
  if (feedbackMode === 'demo') {
    return {
      id: 'feedback',
      title: 'Avaliações da análise',
      blocks: [
        p('Depois de um resultado, você pode dizer se a explicação ajudou e, se quiser, escrever um comentário. Nesta versão, isso é uma demonstração: a avaliação e o comentário não são enviados nem guardados.'),
        p('Quando o envio for real, a avaliação servirá para entender se a explicação foi útil. Ela não mudará o resultado e não será usada como rótulo para treinar o modelo.'),
      ],
    }
  }
  return {
    id: 'feedback',
    title: 'Avaliações da análise',
    blocks: [
      p('Depois de um resultado, você pode dizer se a explicação ajudou e, se quiser, escrever um comentário. Antes de enviar, a tela explica para que serve e como os dados são tratados.'),
      p(`A avaliação serve para entender se a explicação foi útil. Ela não muda o resultado e não é usada como rótulo para treinar o modelo. O comentário é guardado por até ${FEEDBACK_COMMENT_RETENTION_DAYS} dias. O texto analisado não é enviado junto.`),
    ],
  }
}

/** @param {PrivacyConfig} config @returns {Section} */
function controlsSection({ accountsMode }) {
  return {
    id: 'controles',
    title: 'Seus controles',
    blocks: [
      ul([
        'Excluir uma verificação do histórico, com a opção de desfazer.',
        'Limpar todo o histórico deste navegador.',
        'Desligar o histórico, para que as próximas verificações não sejam guardadas.',
        ...(accountsMode === 'off' ? [] : ['Sair da conta, vincular ou desvincular o histórico e excluir a conta, em “Minha conta”.']),
        'Limpar os dados do site no seu navegador, o que apaga o histórico, o contador de visitante e o identificador anônimo.',
      ]),
    ],
  }
}

/** @param {PrivacyConfig} config @returns {Section | null} */
function demoSection({ accountsMode, feedbackMode }) {
  if (accountsMode !== 'demo' && feedbackMode !== 'demo') return null
  const items = []
  if (accountsMode === 'demo') items.push('Entrar, criar conta, recuperar acesso e excluir conta: simulados, só neste navegador.')
  if (feedbackMode === 'demo') items.push('Avaliação da análise: o botão funciona, mas nada é enviado nem guardado.')
  return {
    id: 'demonstracao',
    title: 'O que é demonstração nesta versão',
    blocks: [
      p('Alguns recursos ainda não têm um servidor por trás. Eles aparecem com o aviso “DEMONSTRAÇÃO” no topo da página e funcionam assim:'),
      ul(items),
      p('A análise de texto, o resultado e o histórico neste navegador são reais.'),
    ],
  }
}

/** @returns {Section} */
function pendingSection() {
  return {
    id: 'pendencias',
    title: 'O que a equipe ainda vai definir',
    blocks: [
      p('Esta página descreve o que o sistema faz hoje. Antes de virar um produto aberto ao público, a equipe ainda precisa definir:'),
      ul([
        'por quanto tempo os registros técnicos das análises ficam guardados no servidor;',
        'a finalidade formal e a base legal do tratamento de dados;',
        'o canal para você tirar dúvidas ou pedir informações sobre os seus dados;',
        'a revisão jurídica deste texto.',
      ]),
    ],
  }
}

/**
 * Seções na ordem de leitura.
 * @param {PrivacyConfig} config
 * @returns {Section[]}
 */
export function privacySections(config) {
  const demo = demoSection(config)
  return [
    contentSection(config),
    visitorSection(config),
    historySection(),
    accountsSection(config),
    feedbackSection(config),
    controlsSection(config),
    ...(demo ? [demo] : []),
    pendingSection(),
  ]
}
