import '@fontsource/roboto/latin-400.css'
import '@fontsource/roboto/latin-500.css'
import '@fontsource/roboto/latin-700.css'
import '@fontsource/stix-two-text/latin-400.css'
import '@fontsource/stix-two-text/latin-500.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { createServices } from './services/index.js'
import { AnalysisRunProvider } from './state/analysisRun.jsx'
import { ServicesProvider } from './state/services.jsx'
import { ToastProvider } from './state/toast.jsx'
import './styles/index.css'

// Ponto de entrada. Monta os serviços uma única vez (API real, armazenamento do navegador e,
// enquanto a Etapa 4 do back end não existe, gateways de demonstração para conta e avaliação).
// A ordem dos provedores importa: o aviso de ação (toast) e a execução da análise usam o roteador
// e os serviços, então ficam dentro deles.

const services = createServices()
const container = document.getElementById('root')

if (!container) {
  throw new Error('Elemento #root não encontrado em index.html.')
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <ServicesProvider services={services}>
        <ToastProvider>
          <AnalysisRunProvider>
            <App />
          </AnalysisRunProvider>
        </ToastProvider>
      </ServicesProvider>
    </BrowserRouter>
  </StrictMode>,
)
