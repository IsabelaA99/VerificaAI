import { statusOf } from '../../domain/analysis.js'
import { formatDateTime, formatNumber, formatPercent } from '../../domain/format.js'
import { STATUS, STATUS_INFO } from '../../domain/status.js'
import Notice from '../ui/Notice.jsx'
import StatusBadge from '../ui/StatusBadge.jsx'
import RiskScale from './RiskScale.jsx'

// Resultado principal (RF16, RF26): status em linguagem simples primeiro, índice depois, e a
// alegação analisada junto. O que é técnico fica mais abaixo.

/** @param {{ analysis: import('../../domain/analysis.js').Analysis }} props */
export default function VerdictCard({ analysis }) {
  const code = statusOf(analysis)
  const info = STATUS_INFO[code]
  const inconclusive = code === STATUS.INCONCLUSIVE
  const { model, claim } = analysis
  const partial = model.fullyAnalyzed === false

  return (
    <section className="sheet">
      <div className="verdict-banner dark-panel">
        <div>
          <p className="eyebrow">Resultado da análise</p>
          <p>Análise automática feita em {formatDateTime(analysis.createdAt)}</p>
        </div>
        <span className="verdict-banner__mark" aria-hidden="true">
          Apura
        </span>
      </div>

      <div className="verdict">
        <div>
          <StatusBadge code={code} />
          <h2>{info.label}</h2>
          <p>{info.summary}</p>
        </div>
        {!inconclusive && analysis.riskIndex !== null ? (
          <RiskScale value={analysis.riskIndex} />
        ) : (
          <div className="verdict__none">
            <strong>Sem índice</strong>
            <span>Numa análise inconclusiva o índice de risco não é calculado.</span>
          </div>
        )}
      </div>

      <p className="score-note">
        {inconclusive
          ? 'Esta análise não chegou a uma conclusão. Isso não quer dizer que a notícia seja verdadeira nem que seja falsa.'
          : 'O índice é um indicador de risco. Ele não é a probabilidade de a notícia ser falsa nem uma certeza.'}
      </p>

      {model && model.fakeProbability !== null ? (() => {
        const fakeRatio = model.fakeProbability
        const trueRatio = Math.max(0, 1 - model.fakeProbability)
        const fakePct = Math.round(fakeRatio * 100)
        const truePct = Math.round(trueRatio * 100)
        const isUncertainZone = truePct >= 35 && truePct <= 65
        const isHighRisk = fakePct >= 65
        const sem = model.semanticComparison || {}
        const lex = model.lexicalAnalysis || {}
        const hedging = lex.hedging_terms || []
        const isOutOfDomain = Boolean(model.isOutOfDomain)
        const isSatire = model.discourseType === 'satira' || model.trainingScope === 'out_of_domain_satire'
        const isConspiracy = model.discourseType === 'teoria_conspiratoria' || model.discourseType === 'conspiracy_or_theoretical'
        const isTraditionalPress = (model.trainingScope === 'in_domain_press' || model.discourseType === 'factual') && !isSatire && !isConspiracy
        const divergesFromConsensus = sem.consensus_status === 'diverge_consenso' && !isTraditionalPress
        const isDiscrepant = (isOutOfDomain || isConspiracy || isSatire) && truePct >= 50 && !isTraditionalPress

        return (
          <div className="model-prob-card">
            <div className="model-prob-card__header">
              <div>
                <div className="model-prob-card__eyebrow-row">
                  <p className="model-prob-card__eyebrow">Probabilidade calculada pelo modelo</p>
                  {model.discourseLabel ? (
                    <span className="model-prob-card__discourse-pill">
                      {model.discourseLabel}
                    </span>
                  ) : null}
                  {model.isOutOfDomain ? (
                    <span className="model-prob-card__scope-pill">
                      Fora do Escopo de Treino do Modelo
                    </span>
                  ) : null}
                </div>
                <p className="model-prob-card__headline">
                  {fakeRatio >= 0.5 ? (
                    <>
                      <strong>{formatPercent(fakeRatio)}</strong> de chance de ser <strong>falsa</strong>
                    </>
                  ) : (
                    <>
                      <strong>{formatPercent(trueRatio)}</strong> de chance de ser <strong>verdadeira</strong>
                    </>
                  )}
                </p>
                {isDiscrepant ? (
                  <p className="model-prob-card__subheadline">
                    {isSatire
                      ? 'Padrão de redação formal simulado · Conteúdo humorístico e fictício'
                      : 'Padrão de redação da imprensa tradicional (estilo) · Conteúdo contestado por checagens'}
                  </p>
                ) : null}
              </div>
              {model.confidence !== null ? (
                <span className="model-prob-card__confidence">
                  Confiança estatística: {formatPercent(model.confidence)}
                </span>
              ) : null}
            </div>

            <div
              className="model-prob-card__track"
              role="progressbar"
              aria-valuenow={fakePct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Probabilidade calculada pelo modelo de ser falsa"
            >
              <span
                className="model-prob-card__fill model-prob-card__fill--true"
                style={{ width: `${truePct}%` }}
              />
              <span
                className="model-prob-card__fill model-prob-card__fill--fake"
                style={{ width: `${fakePct}%` }}
              />
            </div>

            <div className="model-prob-card__breakdown">
              <span className="model-prob-card__label-true">
                Chance de ser verdadeira: <strong>{formatPercent(trueRatio)}</strong>
              </span>
              <span className="model-prob-card__label-fake">
                Chance de ser falsa: <strong>{formatPercent(fakeRatio)}</strong>
              </span>
            </div>

            {/* Alertas Expositivos de Margem, Risco e Discrepância */}
            {isDiscrepant ? (
              <div className="model-prob-card__alert model-prob-card__alert--danger">
                {isSatire ? (
                  <>
                    <strong>Atenção: Conteúdo Satírico / Paródia Ficcional:</strong>
                    <span>
                      Este texto foi identificado como <strong>Sátira / Humor</strong>. O classificador BERTimbau avalia apenas a forma da escrita (redação culta de estilo jornalístico), o que explica a probabilidade calculada ({formatPercent(trueRatio)} de padrão formal). No entanto, os fatos descritos são intencionalmente fictícios e cômicos, sem respaldo na realidade factual.
                    </span>
                  </>
                ) : (
                  <>
                    <strong>Atenção: Modelo Treinado em Imprensa Tradicional · Use o Fact-Checking:</strong>
                    <span>
                      O classificador BERTimbau foi treinado exclusivamente com matérias da imprensa tradicional (reconhecimento de formato formal jornalístico). Ele não foi treinado para validar teorias históricas ou conspiratórias. Portanto, a probabilidade calculada ({formatPercent(trueRatio)}) avalia apenas o estilo textual da escrita. A verificação factual deste conteúdo depende prioritariamente das <strong>Checagens de Fatos (Fact-Checking)</strong> e do consenso histórico documentado.
                    </span>
                  </>
                )}
                {model.uncertaintyWarning ? (
                  <span className="model-prob-card__alert-note">{model.uncertaintyWarning}</span>
                ) : null}
              </div>
            ) : isUncertainZone ? (
              <div className="model-prob-card__alert model-prob-card__alert--warning">
                <strong>Atenção à margem estatística ({formatPercent(trueRatio)}):</strong>
                <span>
                  {model.uncertaintyWarning ||
                    `Uma probabilidade de ${formatPercent(trueRatio)} (com ${formatPercent(fakeRatio)} de chance de falsidade) reflete alta incerteza do classificador. É frequente em artigos de opinião, ensaios teóricos ou especulações com linguagem culta. Não considere esta porcentagem como atestado de veracidade.`}
                </span>
              </div>
            ) : isHighRisk ? (
              <div className="model-prob-card__alert model-prob-card__alert--danger">
                <strong>Alerta de Alto Risco ({formatPercent(fakeRatio)} de falsidade):</strong>
                <span>
                  {model.uncertaintyWarning ||
                    'O texto apresenta fortes sinais estilísticos de desinformação ou alegações enganosas. Verifique antes de repassar.'}
                </span>
              </div>
            ) : model.uncertaintyWarning ? (
              <div className="model-prob-card__alert model-prob-card__alert--warning">
                <strong>Nota do Especialista:</strong>
                <span>{model.uncertaintyWarning}</span>
              </div>
            ) : null}

            {/* Comparação Semântica e Consenso Histórico/Científico */}
            {sem.consensus_summary && !isTraditionalPress ? (
              <div className="model-prob-card__semantic">
                <div className="model-prob-card__semantic-head">
                  <span className="model-prob-card__semantic-title">Comparação Semântica & Consenso</span>
                  {sem.consensus_status === 'diverge_consenso' ? (
                    <span className="model-prob-card__badge model-prob-card__badge--divergent">Diverge do Consenso</span>
                  ) : sem.consensus_status === 'conforme_consenso' ? (
                    <span className="model-prob-card__badge model-prob-card__badge--compatible">Compatível com Consenso</span>
                  ) : (
                    <span className="model-prob-card__badge model-prob-card__badge--neutral">Debate Teórico / Sem Consenso</span>
                  )}
                </div>
                <p className="model-prob-card__semantic-text">{sem.consensus_summary}</p>
              </div>
            ) : null}

            {/* Marcadores Léxicos de Especulação (Hedging) */}
            {hedging.length > 0 && !isTraditionalPress ? (
              <div className="model-prob-card__hedging">
                <span className="model-prob-card__hedging-label">Expressões de especulação (hedging) detectadas:</span>
                <div className="model-prob-card__chips">
                  {hedging.map((term) => (
                    <span key={term} className="model-prob-card__chip">“{term}”</span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )
      })() : null}

      {partial ? (
        <div className="verdict__partial">
          <Notice tone="warning" title="Só uma parte do texto foi analisada.">
            {model.chunksAnalyzed !== null && model.chunksTotal !== null
              ? `Foram analisados ${formatNumber(model.chunksAnalyzed)} de ${formatNumber(model.chunksTotal)} trechos. `
              : ''}
            O resultado considera apenas a parte analisada.
          </Notice>
        </div>
      ) : null}

      <div className="claim">
        <p className="section-label">Alegação analisada</p>
        <blockquote>
          <p>{claim.summary ? `“${claim.summary}”` : 'Não foi possível resumir a alegação.'}</p>
        </blockquote>
        <p className="claim__note">
          {claim.confirmedByUser
            ? 'Alegação confirmada por você.'
            : 'Resumo feito automaticamente. Ainda não é possível confirmar ou corrigir a alegação nesta versão.'}
        </p>
      </div>
    </section>
  )
}
