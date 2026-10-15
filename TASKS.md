# Fake Eyes — Plano de Tarefas por Etapas

Baseado na especificação **Requisitos do Sistema Fake Eyes v2.2**.
Legenda: `[x]` concluído · `[/]` em andamento · `[ ]` pendente.

---

## Etapa 1 — Backend base + Modelo (atual)

Objetivo: API Django versionada consumindo o BERTimbau V4 local, com
regras de risco, abstenção e rastreabilidade de versões.

### 1.1 Infraestrutura
- [x] Projeto Django `apura/` com settings via variáveis de ambiente
- [x] `requirements.txt`, `Dockerfile` (CPU torch), `docker-compose.yml`, `nginx/`
- [x] `.env.example` e `.gitignore` (pesos do modelo fora do Git)
- [x] SQLite em dev local, PostgreSQL no Docker

### 1.2 Serviço do modelo (`analysis/services/classifier.py`)
- [x] Carregamento singleton thread-safe do modelo local `bert_fakenews_v4/`
      com fallback para o Hugging Face Hub (RF11)
- [x] Seleção automática de dispositivo (MPS / CUDA / CPU)
- [x] Hash SHA-256 dos pesos como identificador de integridade (RF21)
- [x] Fatiamento determinístico por tokens + agregação documentada (RF12)

### 1.3 Pré-processamento (`analysis/services/preprocessing.py`)
- [x] Validação 50–20.000 caracteres sem corte silencioso (RF01)
- [x] Normalização Unicode/espaços, detecção de vazio/corrompido (RF04)
- [x] Verificação heurística de idioma português (RF04)
- [x] Mascaramento de CPF, telefone e e-mail antes de consultas externas e da persistência dos campos derivados; proteção da API e migração dos registros anteriores (RF05)
- [x] T01: mascaramento restrito a campos narrativos; preservação de UUIDs, hashes e versões, com reparo dos metadados técnicos anteriores

### 1.4 Regras de decisão (`analysis/services/risk.py`, `rules/`)
- [x] Indicadores linguísticos auxiliares (RF10)
- [x] Índice de risco 0–100 com pesos versionados em JSON (RF13)
- [x] Faixas de status 0–25 / 25–60 / 60–100 sem lacunas (RF16)
- [x] Abstenção com motivos distintos e prioridade do inconclusivo (RF14)

### 1.5 API v1 (`/api/v1/`)
- [x] `POST /api/v1/analyses/` — análise por texto
- [x] `GET /api/v1/analyses/<id>/` — resultado técnico persistido
- [x] `GET /api/v1/health/` — status e versões dos componentes
- [x] Estrutura de erro documentada `{error: {code, message, action, field}}` (RF27/RF29)
- [x] Persistência sem texto bruto, com versões de modelo/regras/código (RF05, RF21)

### 1.6 Testes
- [x] Unitários: risco, faixas-limite, abstenção, validação, idioma, PII
- [x] Determinismo do fatiamento (tokenizer real)
- [x] Integração da API com classificador simulado
- [x] Teste opcional com o modelo real (`RUN_MODEL_TESTS=1`)

---

## Etapa 2 — Entrada por URL e segurança
- [x] Extração estruturada: título, subtítulo, corpo, autoria, data, domínio com Trafilatura e BeautifulSoup (RF02)
- [x] Tratamento de falhas: rede, HTTP, paywall, antirrobô, popups de consentimento, não textual (RF03)
- [x] Proteção SSRF: validação de todos os IPs resolvidos e de cada redirecionamento antes da conexão; conexão vinculada ao IP público validado (RNF09)
- [x] Testes de segurança SSRF e extração com mocks, incluindo redirecionamento a destino interno e mudança de DNS

## Etapa 3 — Alegação, evidências e síntese LLM
- [x] Identificação e resumo da alegação principal (RF06, RF20)
- [x] Consulta a evidências via Google Fact Check Tools API + fallback de busca pública (RF07)
- [x] Diferencia consulta concluída sem fontes, falha de provedor e resultado parcial; preserva fontes disponíveis (RF07, RF27)
- [/] Classificação fonte × alegação: veredito só influencia o risco quando o texto da alegação checada corresponde aos termos da alegação enviada, na mesma ordem e sem divergência de negação ou números. Resultados relacionados ficam contextuais; falta validação semântica para reconhecer paráfrases com segurança (RF08)
- [x] Síntese explicativa contextual via LLM (Gemini / OpenAI / Síntese Neural) explicando "por isso e por isso"
- [x] Ativação do sinal `evidence_conflict` no cálculo do índice de risco ponderado
- [x] T02: somente fontes verificadas fornecem `evidence_conflict` e satisfazem a regra de evidência mínima; síntese e fontes contextuais não substituem evidência

## Etapa 4 — Contas, limite de visitante e histórico
- [ ] Cadastro, login, logout seguros (RF31, RNF18)
- [ ] Recuperação de acesso com link de uso único (RF32)
- [ ] Limite de 3 análises/24h por identificador anônimo (RF33, RNF19)
- [ ] Histórico sincronizado + exclusão de itens/conta (RF20, RF28, RF34)
- [ ] Feedback útil/não útil com consentimento (RF19)
- [ ] Rate limiting, CSP, CORS restrito, HTTPS (RNF16)

## Etapa 5 — Aplicação web (concluída via frontend/ apuraWeb)
- [x] Páginas: início, análise, resultado, histórico, sobre, privacidade (RF23, RF30)
- [x] Formulário texto/URL com validação acessível (RF24)
- [x] Estados reais de processamento, sem progresso fictício (RF25, RNF17)
- [x] Resultado, fontes, orientação e resumo copiável (RF16–RF18, RF26)
- [x] WCAG 2.2 AA, responsivo 320–1.440 px, matriz de navegadores (RNF08, RNF14, RNF15)
- [x] Testes automatizados com Vitest cobrindo fluxos, jornada e a11y axe

## Etapa 6 — Qualidade da IA e governança
- [ ] Calibração (temperature scaling) em dados independentes (RNF04)
- [ ] Definição do limiar de abstenção com conjunto de validação (RF14)
- [ ] Relatório por fonte/período/tema e fora do escopo (RNF03, RNF05)
- [ ] Rastreamento de experimentos e reprodutibilidade (RNF06)
- [ ] CI executando testes e bloqueando publicação em falhas (RNF13)
- [ ] Teste de desempenho p50/p95/p99 ≤ 30 s (RNF01)
