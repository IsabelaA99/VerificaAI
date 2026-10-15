import { useMemo } from 'react'
import { SOURCE_RELATION_LABELS } from '../../domain/analysis.js'
import { AppError } from '../../domain/errors.js'
import { formatDate } from '../../domain/format.js'
import ErrorPanel from '../analysis/ErrorPanel.jsx'
import Button from '../ui/Button.jsx'
import Icon from '../ui/Icon.jsx'
import Notice from '../ui/Notice.jsx'

// Fontes e evidências externas (RF07, RF08, RF17). Esta seção só trata de evidências de fora:
// os sinais do modelo e do texto ficam em outras seções, separados (RF08, RF17).
//
// Os quatro estados vêm de analysis.evidence.status:
//   disabled → a consulta a fontes não está ligada no back end (é o caso hoje, antes da Etapa 3);
//   none     → consultou e não achou fonte relevante: "evidências insuficientes" (RF07);
//   failed   → a consulta falhou (RF27, cenário 6): a análise continua, mas limitada;
//   found    → cartões de fonte com os campos do RF08.
// Campo que a fonte não traz aparece como "não informado", nunca inventado.

const RELATION_ICONS = /** @type {const} */ ({
  compatible: 'check',
  conflicting: 'status-attention',
  contextual: 'info',
  insufficient: 'status-inconclusive',
})

const RELATION_TONES = /** @type {const} */ ({
  compatible: 'low',
  conflicting: 'attention',
  contextual: 'neutral',
  insufficient: 'inconclusive',
})

/** @param {string} url */
function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** @param {{ source: import('../../domain/analysis.js').Source }} props */
function SourceCard({ source }) {
  const host = source.url ? hostOf(source.url) : ''
  return (
    <article className="source">
      <div className="source__head">
        <span className={`pill pill--${RELATION_TONES[source.relation]}`}>
          <Icon name={RELATION_ICONS[source.relation]} size={16} />
          <span>{SOURCE_RELATION_LABELS[source.relation]}</span>
        </span>
        <h3 className="source__title">{source.title ?? 'Título não informado'}</h3>
      </div>
      <p className="source__meta">
        {source.publisher ?? 'Veículo ou instituição não informado'} ·{' '}
        {source.publishedAt ? formatDate(source.publishedAt) : 'Data não informada'}
      </p>
      {source.excerpt ? (
        <blockquote className="source__excerpt">“{source.excerpt}”</blockquote>
      ) : (
        <p className="source__reason">Trecho utilizado não informado.</p>
      )}
      <p className="source__reason">
        <strong>Por que esta fonte aparece: </strong>
        {source.reason ?? 'motivo não informado.'}
      </p>
      <div>
        {source.url ? (
          <Button variant="outline" size="small" href={source.url} external iconEnd="external">
            Abrir a fonte{host ? ` (${host})` : ''}
          </Button>
        ) : (
          <p className="source__reason">Endereço da fonte não informado.</p>
        )}
      </div>
    </article>
  )
}

/**
 * @param {{
 *   analysis: import('../../domain/analysis.js').Analysis,
 * }} props
 */
export default function SourcesSection({ analysis }) {
  const { evidence } = analysis
  const failure = useMemo(
    () => new AppError({ scenario: 'evidence_failure', details: { partial: evidence.sources.length > 0 } }),
    [evidence.sources.length],
  )

  return (
    <section className="sheet sheet--pad result-section">
      <p className="section-label">Evidências externas</p>
      <h2>Fontes consultadas</h2>

      {evidence.status === 'failed' ? (
        <ErrorPanel
          error={failure}
          focusOnMount={false}
          headingLevel={3}
        />
      ) : null}

      {evidence.status === 'disabled' ? (
        <Notice>
          Nesta versão, a consulta a fontes externas ainda não está habilitada. Nenhuma evidência externa foi verificada:
          este resultado vem só do texto enviado.
        </Notice>
      ) : null}

      {evidence.status === 'none' ? (
        <Notice>
          Nenhuma fonte relevante foi encontrada, então as evidências são insuficientes. Não vamos inventar referências
          para preencher a resposta.
        </Notice>
      ) : null}

      {evidence.sources.length ? (
        <div>
          {evidence.sources.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
        </div>
      ) : null}
    </section>
  )
}
