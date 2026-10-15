import { useState } from 'react'
import { useParams } from 'react-router-dom'
import ErrorPanel from '../components/analysis/ErrorPanel.jsx'
import PageHeading from '../components/layout/PageHeading.jsx'
import ExplanationSection from '../components/result/ExplanationSection.jsx'
import FeedbackPanel from '../components/result/FeedbackPanel.jsx'
import IndicatorsSection from '../components/result/IndicatorsSection.jsx'
import LimitationsSection from '../components/result/LimitationsSection.jsx'
import NextSteps from '../components/result/NextSteps.jsx'
import ShareSummary from '../components/result/ShareSummary.jsx'
import SourcesSection from '../components/result/SourcesSection.jsx'
import TechnicalDetails from '../components/result/TechnicalDetails.jsx'
import VerdictCard from '../components/result/VerdictCard.jsx'
import Button from '../components/ui/Button.jsx'
import { useAnalysisResult } from '../hooks/useAnalysisResult.js'
import { useDocumentTitle } from '../hooks/useDocumentTitle.js'

// Página de resultado (RF16, RF17, RF18, RF26).
//
// Ordem na página (RF26: resultado principal antes dos detalhes técnicos):
//   status e índice → próximo passo → fatores → fontes → indicadores → limitações → detalhes
//   técnicos. Compartilhar e avaliar ficam na coluna lateral (embaixo, em telas pequenas).
//
// O resultado vem do cache da página (acabou de chegar) ou da API, pelo identificador na
// endereço. Por isso o link do histórico funciona depois de recarregar.

/** @param {{ id: string | undefined, onRetryLoad: () => void }} props */
function ResultView({ id, onRetryLoad }) {
  const state = useAnalysisResult(id)
  useDocumentTitle(
    state.status === 'error' ? 'Resultado indisponível' : state.status === 'loading' ? 'Carregando resultado' : 'Resultado da análise',
  )

  if (state.status === 'loading') {
    return (
      <div className="wrap screen appear">
        <PageHeading eyebrow="Relatório de verificação" title="Resultado da análise" />
        <div className="sheet sheet--pad loading-sheet" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>Carregando o resultado…</p>
        </div>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="wrap screen appear">
        <PageHeading eyebrow="Relatório de verificação" title="Resultado da análise" />
        <ErrorPanel
          error={state.error}
          headingLevel={2}
          focusOnMount={false}
          onAction={(action) => {
            if (action === 'retry') onRetryLoad()
            else if (action === 'reload') window.location.reload()
          }}
        />
      </div>
    )
  }

  const { analysis } = state

  return (
    <div className="wrap screen appear">
      <PageHeading
        eyebrow="Relatório de verificação"
        title="Resultado da análise"
        lead="O contexto faz a diferença. Aqui estão o resultado, os sinais e os próximos passos."
        action={
          <Button to="/" variant="outline" size="small" iconEnd="arrow">
            Nova verificação
          </Button>
        }
      />

      <div className="result-grid">
        <div className="result-main">
          <VerdictCard analysis={analysis} />
          <NextSteps analysis={analysis} />
          <ExplanationSection analysis={analysis} />
          <SourcesSection analysis={analysis} />
          <IndicatorsSection indicators={analysis.indicators} />
          <LimitationsSection limitations={analysis.limitations} />
          <TechnicalDetails analysis={analysis} />
        </div>
        <aside className="result-side" aria-label="Compartilhar e avaliar">
          <ShareSummary analysis={analysis} />
          <FeedbackPanel key={analysis.id} analysisId={analysis.id} />
        </aside>
      </div>
    </div>
  )
}

export default function ResultPage() {
  const { id } = useParams()
  // Mudar a chave remonta a página e busca o resultado de novo ("Tentar de novo").
  const [attempt, setAttempt] = useState(0)
  return <ResultView key={`${id}-${attempt}`} id={id} onRetryLoad={() => setAttempt((n) => n + 1)} />
}
