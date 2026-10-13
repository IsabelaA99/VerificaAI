# verificAI — Fake Eyes / Apura

Sistema completo de apoio à avaliação de notícias e alegações em língua portuguesa, integrando backend **Django + Django REST Framework**, modelo de NLP **BERTimbau V4 (com fatiamento determinístico e tokens de separação `[SEP]`)** e frontend moderno **ApuraWeb (React 19 + Vite 8)**.

Plano de entrega por etapas da especificação: [TASKS.md](TASKS.md).

---

## Estrutura do Projeto

```text
verificAI/
├── apura/                      # Backend Django
│   ├── manage.py
│   ├── apura/                  # settings, urls, wsgi
│   └── analysis/               # App de análise (API v1, regras, fatiamento)
│       ├── api/                # API REST v1 (views, serializers, erros)
│       ├── services/           # classifier, preprocessing, risk, pipeline
│       ├── rules/rules_v1.json # Pesos e limiares versionados
│       └── tests/
├── frontend/                   # Interface Web (React 19 + Vite 8)
│   ├── src/                    # Componentes, páginas, domínio, estado, estilos
│   ├── public/                 # Favicons, manifesto e robôs
│   ├── deploy/                 # Configuração Nginx e cabeçalhos de segurança
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── bert_fakenews_v4/           # Pesos e tokenizer do BERTimbau (Git LFS)
│   ├── config.json
│   ├── model.safetensors       # Pesos binários (~436 MB)
│   ├── tokenizer.json
│   └── tokenizer_config.json
├── docker-compose.yml          # Orquestração (db, web, nginx/frontend)
├── Dockerfile                  # Imagem do backend Django
├── requirements.txt            # Dependências Python
└── .env.example
```

---

## Arquitetura de Machine Learning & Lógica de `[SEP]`

O modelo de classificação textual é baseado no **BERTimbau** (`neuralmind/bert-base-portuguese-cased`), ajustado para classificação de desinformação em língua portuguesa com representação estruturada de matérias jornalísticas.

### 1. Formato de Entrada e Tokens Especiais

O modelo foi treinado para discernir diferentes seções de uma publicação jornalística através dos tokens separadores:

$$\text{[CLS] título [SEP] subtítulo [SEP] trecho\_do\_corpo [SEP]}$$

* **Token `[CLS]` (ID 101):** Inicia a sequência e sua representação no topo da rede é utilizada pela cabeça de classificação.
* **Tokens `[SEP]` (ID 102):** Delimitam explicitamente as fronteiras sintáticas entre **Título**, **Subtítulo** e **Corpo**.
* **Prefixo Preservado:** Título e subtítulo contêm a essência da alegação e são repetidos em todas as janelas fatiadas da notícia. Se o prefixo exceder 50% de `MAX_LEN` (128 tokens), ele é truncado deterministicamente com aviso (`prefix_truncated`).

### 2. Tratamento de Entrada Não Estruturada

Quando o usuário cola um texto único no formulário sem preencher campos separados:
* A função `_infer_title` em `preprocessing.py` analisa a primeira linha: se tiver entre 10 e 200 caracteres e for sucedida por quebra de linha, é isolada como título da matéria (`title_inferred = True`).
* Se não houver quebra de linha, os slots sintáticos são mantidos com `[CLS] [SEP] [SEP] {corpo} [SEP]`, assegurando alinhamento posicional nos embeddings.
* Via API REST (`/api/v1/analyses/`), é possível enviar opcionalmente os campos `title` e `subtitle` de forma direta e estruturada.

### 3. Fatiamento Determinístico (*Chunking* com *Stride*)

Para processar matérias longas (até o limite de 20.000 caracteres) sem perda de contexto:
* O corpo é fatiado em janelas com sobreposição (*stride*) de tokens.
* Os cortes são alinhados ao início de palavras inteiras (nenhuma janela se inicia com sub-palavras `##`).
* Todas as janelas são processadas pelo modelo e agregadas via média aritmética das probabilidades $P(\text{falsa})$.

---

## Sistema Estritamente Probabilístico & Governança de Risco

> **Princípio Fundamental:** O sistema Fake Eyes **não emite certezas factuais absolutas**. Todo resultado é um indicador de risco estatístico/probabilístico baseado em padrões textuais aprendidos.

### 1. Métricas do Modelo

* **`fake_probability`:** Média de $P(\text{falsa})$ entre todos os trechos analisados (0.0 a 1.0).
* **`confidence`:** Distância da incerteza, dada por $\max(p, 1 - p)$.
* **`chunk_disagreement`:** Desvio-padrão das probabilidades entre as diferentes janelas da matéria.

### 2. Regra de Abstenção Estatística (RF14)

Quando a probabilidade é incerta ou o texto gera sinais contraditórios entre seus trechos:
* Se $\text{confiança} < 0.70$ (modelo próximo da dúvida) OU $\text{desacordo} > 0.35$ (trechos com previsões conflitantes):
  * O status se torna obrigatoriamente **`analise_inconclusiva`**.
  * O índice numérico é omitido (`risk_index = null`), evitando induzir o usuário a conclusões arbitrárias.

### 3. Índice de Risco (0 a 100)

Quando conclusivo, o índice pondera:
* **70%**: Probabilidade de falsidade do BERTimbau.
* **30%**: Indicadores linguísticos heurísticos (palavras em caixa alta, pontuação excessiva, termos sensacionalistas).

Faixas de risco sem sobreposição:
* **0 a 25:** *Poucos sinais de risco*
* **Acima de 25 a 60:** *Requer atenção*
* **Acima de 60 a 100:** *Alto risco*

---

## Exibição de Métricas no Front-end (ApuraWeb)

A interface web foi desenhada para comunicar incerteza probabilística com clareza, em conformidade com as diretrizes de acessibilidade **WCAG 2.2 AA**:

* **Card de Veredito (`VerdictCard.jsx` e `RiskScale.jsx`):**
  * Apresenta o status e a escala contínua de 0 a 100 (*bullet graph* de Stephen Few).
  * Exibe nota explicativa destacada: *"O índice é um indicador de risco. Ele não é a probabilidade de a notícia ser falsa nem uma certeza."*
  * Em caso de abstenção: *"Esta análise não chegou a uma conclusão. Isso não quer dizer que a notícia seja verdadeira nem que seja falsa."*
* **Painel Retrátil de Detalhes Técnicos (`TechnicalDetails.jsx`):**
  * Revela os valores estatísticos brutos: classe predita, $P(\text{falsa})$, índice de confiança, quantidade de trechos analisados e tokens processados.
  * Informa pesos, sinais e a fórmula matemática utilizada.
  * Exibe rastreabilidade técnica: versão do modelo `bertimbau-fakenews-v4` e hash SHA-256 dos pesos binários.
* **Limitações Éticas e Recomendações (`LimitationsSection.jsx`):**
  * Orienta o usuário a checar fontes originais e veículos de jornalismo profissional antes de compartilhar conteúdos.

---

## Gerenciamento de Arquivos Grandes (Git LFS)

O arquivo de pesos do modelo (`bert_fakenews_v4/model.safetensors`, ~436 MB) é rastreado via **Git LFS (Large File Storage)** através do arquivo `.gitattributes`.

### Clonando com Git LFS

```bash
# 1. Instalar o Git LFS no sistema (se ainda não tiver)
# macOS: brew install git-lfs
# Ubuntu/Debian: sudo apt install git-lfs

# 2. Inicializar o Git LFS
git lfs install

# 3. Baixar os pesos binários rastreados
git lfs pull
```

> **Fallback Inteligente:** Se o repositório for clonado sem Git LFS (onde `model.safetensors` é apenas um ponteiro de texto de ~130 bytes), o backend detecta isso automaticamente e baixa os pesos diretamente do **Hugging Face Hub** (`oficialmarlon/bertimbau-fakenews-detector-v4`), mantendo tudo funcional sem erros. Em Apple Silicon (Mac M1–M4), a inferência utiliza aceleração de hardware Metal (MPS) automaticamente.

---

## Rodando Localmente (Sem Docker)

### 1. Back end (Django + BERTimbau)
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # ajuste DJANGO_SECRET_KEY
cd apura
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py runserver
```

A API estará rodando em `http://localhost:8000`.

### 2. Front end (React 19 + Vite 8)
```bash
cd frontend
npm ci
npm run dev
```

A aplicação web estará acessível em `http://localhost:5173`. O proxy do Vite encaminha chamadas de `/api` diretamente para o Django (`http://localhost:8000`).

---

## Rodando com Docker (Full-Stack)

```bash
cp .env.example .env          # defina DJANGO_SECRET_KEY e DJANGO_DEBUG=false
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py collectstatic --no-input
```

* **`http://localhost`**: Interface web (SPA React servida pelo Nginx).
* **`http://localhost/api/`**: API Django REST Framework.
* **`http://localhost/admin/`**: Painel administrativo do Django.

---

---

## Pipeline de Checagem: Raspagem Web, Google Fact Check e Síntese LLM

O sistema implementa um pipeline integrado de ponta a ponta:

```text
Entrada (Texto ou Link) 
   │
   ├── [Se Link] ──> Validação SSRF ──> Raspagem (Trafilatura) ──> Extração Limpa (sem popups/cookies)
   │
   ├── [IA Local] ──> Fatiamento com [SEP] ──> BERTimbau V4 ──> P(falsa), Confiança, Chunk Disagreement
   │
   ├── [Linguística] ──> Indicadores Estilísticos (Caixa alta, exclamações, termos sensacionalistas)
   │
   ├── [Fact-Checking] ──> Google Fact Check Tools API / Agências de Checagem Brasileiras
   │
   └── [Síntese LLM] ──> Gemini / OpenAI / Motor Especializado ──> Explicação ("por isso e por isso")
```

### 1. Raspagem de Notícias por URL (Bypass de Popups e Modais)
* Utiliza a biblioteca **Trafilatura** configurada com cabeçalhos realistas de navegador desktop para extrair o miolo da notícia, descartando automaticamente popups de consentimento de cookies, modais publicitários, cabeçalhos de navegação e rodapés.
* Fallback integrado com **BeautifulSoup** para inspeção de metadados OpenGraph (`og:title`, `og:description`) e estrutura `<article>`.
* **Proteção Estrita contra SSRF (RNF09):** Bloqueio de IPs locais, redes privadas (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12), loopback, link-local e metadados de nuvem (169.254.169.254).

### 2. Integração com Google Fact Check Tools & Agências
* Consulta a API oficial do Google Fact Check (`factchecktools.googleapis.com`) em busca de análises prévias registradas via *ClaimReview*.
* Fallback automático para veículos de checagem brasileiros (*G1 Fato ou Fake*, *Aos Fatos*, *Agência Lupa*, *Boatos.org*, *E-farsas*, *UOL Confere*).
* Classifica a relação de cada fonte encontrada como **Conflitante** (*conflicting*), **Compatível** (*compatible*) ou **Contextual** (*contextual*).

### 3. Síntese Explicativa via LLM ("Por isso e por isso")
* Cruza a avaliação probabilística da IA com os achados de checagem na internet e os gatilhos de linguagem.
* Suporta **Google Gemini** (`gemini-2.0-flash`), **OpenAI** (`gpt-4o-mini`) ou **Groq** via chaves de API no `.env`.
* **Fallback Analítico Inteligente:** Caso nenhuma chave esteja configurada ou o serviço externo esteja indisponível, um motor analítico jornalístico determinístico gera a síntese estruturada sem quebrar a experiência do usuário.

---

## API REST v1

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/v1/health/?load=1` | Status do serviço, versões e informações do modelo carregado |
| `POST` | `/api/v1/analyses/` | Submete uma análise síncrona por **texto** ou por **link** (≤ 30s) |
| `GET` | `/api/v1/analyses/<id>/` | Recupera resultado persistido e versões técnicas |

### Exemplo de Requisição por Link (POST `/api/v1/analyses/`)

```json
{
  "input_type": "url",
  "url": "https://g1.globo.com/fato-ou-fake/noticia/2026/01/01/exemplo-materia.ghtml"
}
```

### Exemplo de Resposta (Status 201 Created)

```json
{
  "id": "e87ac338-8a06-4fb7-9a45-aec1cd52fcd2",
  "api_version": "v1",
  "created_at": "2026-10-09T15:20:00Z",
  "input_type": "url",
  "status": {
    "code": "alto_risco",
    "label": "Alto risco"
  },
  "risk_index": 88.5,
  "claim": {
    "summary": "Nova substância milagrosa cura todas as doenças em 24h",
    "confirmed_by_user": false
  },
  "explanation": [
    "Esta notícia apresenta alta probabilidade de ser falsa (94% segundo o modelo BERTimbau) e o conteúdo foi contestado por agências de checagem na internet.",
    "O modelo BERTimbau identificou probabilidade de 94% de conteúdo enganoso com base em padrões textuais característicos de desinformação.",
    "Foram encontradas checagens de fatos que desmentem as alegações centrais da matéria.",
    "Foram encontradas expressões apelativas: “urgente”, “milagrosa”."
  ],
  "evidence": {
    "enabled": true,
    "status": "found",
    "sources": [
      {
        "id": "gfc-1",
        "relation": "conflicting",
        "publisher": "Agência Lupa",
        "title": "É falso que substância cura todas as doenças",
        "excerpt": "Alegação desmentida por autoridades sanitárias.",
        "url": "https://lupa.uol.com.br/artigo-exemplo",
        "relation_reason": "Classificado como Falso pela checagem oficial."
      }
    ]
  },
  "model": {
    "label": "falsa",
    "fake_probability": 0.942,
    "confidence": 0.942,
    "chunks_analyzed": 1,
    "chunks_total": 1,
    "chunk_disagreement": 0.0,
    "tokens_analyzed": 58,
    "tokens_total": 58,
    "fully_analyzed": true,
    "aggregation": "mean"
  },
  "risk": {
    "value": 88.5,
    "formula": "100 * sum(w_i * s_i) / sum(w_i)",
    "weights": {
      "model_fake_probability": 0.7,
      "linguistic_indicators": 0.3
    }
  },
  "limitations": [
    "O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.",
    "O índice de risco é um indicador e não representa a probabilidade de a notícia ser falsa."
  ],
  "versions": {
    "model": "bertimbau-fakenews-v4",
    "model_sha256": "...",
    "rules": "1.0",
    "code": "251f63c"
  }
}
```

---

## Testes Automatizados

### Back end (Django + Pytest/Unittest)
```bash
cd apura
../.venv/bin/python manage.py test analysis                    # Testes rápidos com classificador simulado
RUN_MODEL_TESTS=1 ../.venv/bin/python manage.py test analysis  # Testes com inferência real do modelo
```

### Front end (React / Vitest)
```bash
cd frontend
npm test               # Executa os 808 testes automatizados
npm run check          # Lint + typecheck + testes + build de produção
```
