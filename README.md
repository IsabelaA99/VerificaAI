# verificAI — Apura

Sistema completo de apoio à avaliação de notícias e alegações em língua portuguesa, integrando backend **Django + Django REST Framework**, modelo de NLP **BERTimbau V4 (com fatiamento determinístico e tokens de separação `[SEP]`)**, frontend moderno **ApuraWeb (React 19 + Vite 8)** e **extensão de navegador** para Chrome e Firefox.

Plano de entrega por etapas da especificação: [TASKS.md](TASKS.md).

---

## Estrutura do Projeto

```text
verificAI/
├── apura/                      # Backend Django
│   ├── manage.py
│   ├── apura/                  # settings, urls, wsgi
│   └── analysis/               # App de análise (API v1, regras, fatiamento)
│       ├── api/                # API REST v1 (views, serializers, throttling, erros)
│       ├── services/           # classifier, preprocessing, risk, pipeline
│       ├── rules/rules_v1.json # Pesos e limiares versionados
│       └── tests/
├── extension/                  # Extensão de navegador (Chrome & Firefox)
│   ├── manifest.json           # Manifest V3 (compatível com Chrome e Firefox ≥ 109)
│   ├── popup.html              # Interface da extensão
│   ├── popup.css               # Estilos (identidade visual navy+gold do ApuraWeb)
│   ├── popup.js                # Lógica do popup: estados, fetch à API, renderização
│   └── content.js              # Script injetado na página: extrai título e conteúdo
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

## Extensão de Navegador (Chrome & Firefox)

A extensão **ApuraWeb** permite verificar a confiabilidade de qualquer notícia diretamente no navegador, sem copiar e colar texto, sem limite de uso por cliente.

### Funcionalidades

- **Análise com um clique** — o usuário abre o artigo e pressiona o botão; o texto é extraído e enviado ao servidor local automaticamente.
- **Extração inteligente de conteúdo** — o `content.js` ignora menus, rodapés, sidebars, anúncios e comentários, retornando apenas o corpo do artigo; prioriza `og:title` e detecta o contêiner semântico da notícia.
- **Resultado visual imediato** — banner de veredito com ícone e cor por faixa de risco (✅ Seguro / ⚠️ Atenção / 🚨 Alto risco / 🔍 Inconclusivo), barra de risco animada (0–100) e estatísticas rápidas (rótulo do modelo, probabilidade, confiança).
- **Modal de detalhes completos** — ao clicar em "Ver análise completa", abre um painel com cinco seções: Veredito, Explicação, O que fazer, Fontes verificadas e Dados técnicos (id, tempo de análise, tokens, versões).
- **Identidade visual** alinhada ao site ApuraWeb: paleta azul-marinho e dourado, tipografia Roboto + STIX Two Text.
- **Sem quota de uso** — requisições identificadas com `X-Client-Source: browser-extension` são isentas do throttle do servidor.

### Como instalar (modo desenvolvedor)

> O servidor Django precisa estar rodando em `http://127.0.0.1:8000` antes de usar a extensão.

#### Chrome / Edge / Brave

1. Acesse `chrome://extensions` (ou `edge://extensions` / `brave://extensions`)
2. Ative o **Modo do desenvolvedor** (canto superior direito)
3. Clique em **Carregar sem compactação**
4. Selecione a pasta `extension/` do repositório

#### Firefox

1. Acesse `about:debugging#/runtime/this-firefox`
2. Clique em **Carregar extensão temporária…**
3. Selecione o arquivo `extension/manifest.json`

> A extensão permanece instalada enquanto o Firefox estiver aberto. Para uso permanente no Firefox, é necessário assinar a extensão via [addons.mozilla.org](https://addons.mozilla.org).

### Integração com o backend

| Aspecto | Detalhe |
|---|---|
| Endpoint | `POST http://127.0.0.1:8000/api/v1/analyses/` |
| Payload enviado | `{ input_type: "text", title, text }` |
| Header de identificação | `X-Client-Source: browser-extension` |
| Throttle | **Isento** — sem quota por cliente para a extensão |
| CORS | Liberado para `chrome-extension://` e `moz-extension://` |
| Formato da resposta | Objeto simplificado com `result.verdict_code`, `result.score`, `result.explanation`, `result.full_details` |

### Exemplo de resposta da API para a extensão

```json
{
  "status": "ok",
  "result": {
    "verdict_code": "DANGER",
    "label": "Alto risco",
    "score": "85/100",
    "risk_index": 84.91,
    "summary": "Esta notícia apresenta alta probabilidade de ser falsa...",
    "model_label": "Falsa",
    "fake_probability": 99.8,
    "confidence": 99.8,
    "explanation": ["..."],
    "recommendations": ["..."],
    "evidence": { "sources": [...] },
    "limitations": ["..."],
    "full_details": { ... }
  }
}
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
* Apenas a **primeira janela** é pontuada pelo modelo, o mesmo que a inferência de referência do [repositório do modelo](https://github.com/oficialmarlonmd/DataScience-Trainfakenews-model) (entrada truncada em 128 tokens). No treino da V4, as notícias verdadeiras foram fatiadas em trechos tirados do meio do texto e as falsas entraram inteiras; por isso o modelo classifica como "verdadeira" qualquer janela que não começa no início do corpo, mesmo em notícias falsas. A média entre janelas derrubava a acurácia no teste cego de 100 notícias do modelo de 98% para 87%.
* Quando o texto não cabe em uma janela, `fully_analyzed` é `false` e o resultado informa que parte do conteúdo não foi analisada.

---

## Sistema Estritamente Probabilístico & Governança de Risco

> **Princípio Fundamental:** O sistema Apura **não emite certezas factuais absolutas**. Todo resultado é um indicador de risco estatístico/probabilístico baseado em padrões textuais aprendidos.

### 1. Métricas do Modelo

* **`fake_probability`:** $P(\text{falsa})$ da primeira janela da matéria (0.0 a 1.0).
* **`confidence`:** Distância da incerteza, dada por $\max(p, 1 - p)$.
* **`chunk_disagreement`:** Desvio-padrão das probabilidades entre as janelas pontuadas; com uma única janela pontuada, é sempre 0.

### 2. Regra de Abstenção Estatística (RF14)

Quando a probabilidade é incerta ou o texto gera sinais contraditórios entre seus trechos:
* Se $\text{confiança} < 0.70$ (modelo próximo da dúvida) OU $\text{desacordo} > 0.35$ (trechos com previsões conflitantes):
  * O status se torna obrigatoriamente **`analise_inconclusiva`**.
  * O índice numérico é omitido (`risk_index = null`), evitando induzir o usuário a conclusões arbitrárias.

### 3. Índice de Risco (0 a 100)

Quando conclusivo, o índice usa os pesos de `rules_v1.json`:
* **60%**: pontuação de falsidade do BERTimbau.
* **15%**: indicadores linguísticos heurísticos (palavras em caixa alta, pontuação excessiva, termos sensacionalistas).
* **25%**: conflito com checagens externas, quando esse sinal está disponível.

Sinais ausentes são excluídos e os pesos restantes são normalizados. Sem checagens classificadas como compatíveis ou conflitantes, o índice usa **80%** do modelo e **20%** dos indicadores linguísticos. Esses pesos e limiares são provisórios até a calibração e a validação das fontes.

A síntese por IA não substitui fontes verificadas no sinal `evidence_conflict` nem na regra de
evidência mínima. A configuração atual usa `require_evidence=false`; quando essa regra é ativada,
ausência de fontes compatíveis ou conflitantes gera `insufficient_evidence`, mesmo que a síntese
declare consenso. Fontes apenas contextuais não satisfazem a regra. Uma consulta parcial pode
preservar evidência de uma fonte verificada, mantendo o aviso de que outras consultas falharam.

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

O modelo é pré-carregado durante a inicialização (`MODEL_WARMUP=true`). Aguarde o
servidor indicar que está pronto antes de abrir uma análise. A inicialização pode
demorar mais na primeira execução; esse custo deixa de ocorrer no primeiro envio.

As etapas de análise compartilham um prazo de 27 segundos, deixando margem para
responder antes do timeout de 30 segundos da interface. A extração de URL tem até
8 segundos; a consulta a fontes, até 8 segundos; e todos os provedores de síntese
juntos, até 7 segundos, sempre respeitando o tempo restante. Comprova, Boatos.org e
Wikipédia são consultados em paralelo. Fontes que não terminam no prazo são
sinalizadas como consulta incompleta; a síntese usa o fallback local quando a IA
externa atrasa. Se a extração ou o modelo não terminarem no prazo, a API responde
`504` com `analysis_timeout`, sem persistir um resultado tardio. O banco e o
transporte também precisam estar saudáveis para cumprir o prazo ponta a ponta.

Os logs `analysis stage=model|sources|explanation|scrape ms=...` mostram o tempo
de cada etapa sem registrar o texto analisado. Chamadas já iniciadas podem terminar
em segundo plano após um timeout; há um limite de oito tarefas por processo, sem
fila ilimitada. Os testes de latência usam serviços lentos simulados; não medem
a disponibilidade real dos provedores.

### 2. Extensão de Navegador

Com o backend rodando, carregue a extensão no navegador (ver seção [Como instalar](#como-instalar-modo-desenvolvedor) acima). Não há etapa de build — os arquivos da pasta `extension/` são carregados diretamente.

### 3. Front end (React 19 + Vite 8)
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

> A extensão de navegador continua funcionando com Docker — basta apontar `SERVER_URL` em `extension/popup.js` para `http://localhost/api/v1/analyses/` se quiser usar o stack completo em vez do `runserver` local.

---

## Pipeline de Checagem: Raspagem Web, Google Fact Check e Síntese LLM

O sistema implementa um pipeline integrado de ponta a ponta:

```text
Entrada (Texto, Link ou Extensão de Navegador)
   │
   ├── [Extensão] ──> Extração do artigo via content.js ──> Enviado como texto estruturado
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
* **Proteção contra SSRF (RNF09):** Valida todos os IPs resolvidos e cada redirecionamento antes de conectar. A conexão usa o IP público aprovado, preservando o nome do site nos cabeçalhos, no TLS e na verificação do certificado. A cadeia de redirecionamentos é limitada a cinco saltos.

### 2. Integração com Google Fact Check Tools & Agências
* Consulta a API oficial do Google Fact Check (`factchecktools.googleapis.com`) em busca de análises prévias registradas via *ClaimReview*.
* Se a API não trouxer alegações relacionadas, consulta Projeto Comprova, Boatos.org e Wikipédia como alternativas.
* Só usa o veredito para classificar uma fonte como **Conflitante** (*conflicting*) ou **Compatível** (*compatible*) quando os termos da alegação checada correspondem aos da alegação analisada, na mesma ordem e sem divergência de negação ou números. Fontes relacionadas, mas sem correspondência segura, ficam **Contextuais** (*contextual*) e não entram como evidência na síntese nem no sinal de conflito. A regra é conservadora e não reconhece todas as paráfrases; confira o link original.

### 3. Síntese Explicativa via LLM ("Por isso e por isso")
* Cruza a avaliação probabilística da IA com os achados de checagem na internet e os gatilhos de linguagem.
* Tenta **Groq**, **Google Gemini** e **OpenAI**, nessa ordem, quando as respectivas chaves estão configuradas, compartilhando o prazo da etapa.
* **Fallback Analítico Inteligente:** Caso nenhuma chave esteja configurada ou o serviço externo esteja indisponível, um motor analítico jornalístico determinístico gera a síntese estruturada sem quebrar a experiência do usuário.

A resposta externa precisa cumprir o contrato antes de entrar no pipeline: resumo não vazio,
lista de pontos textuais, objetos semântico e lexical com tipos corretos, booleanos e valores
permitidos. Não há conversão automática de números para texto ou de texto para lista. Campos
opcionais ausentes recebem valores neutros e campos extras são ignorados. Os limites são de
4.000 caracteres para resumo e detalhes, até 10 pontos de 1.000 caracteres e até 20 termos
de 200 caracteres. Resposta inválida permite tentar o próximo provedor; sem uma resposta válida
no prazo, usa-se a síntese local. Somente a explicação aceita chega à persistência.

Ao ler um resultado anterior com explicação estruturalmente inválida, a API omite essa explicação
complementar e informa a limitação. Essa leitura não chama a IA nem altera o registro salvo.

---

## API REST v1

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/v1/health/?load=1` | Status do serviço, versões e informações do modelo carregado |
| `POST` | `/api/v1/analyses/` | Submete uma análise síncrona por **texto**, **link** ou **extensão** (≤ 30s) |
| `GET` | `/api/v1/analyses/<id>/` | Recupera resultado persistido e versões técnicas |

### Privacidade dos resultados

O texto integral é usado na análise local, mas não é salvo como campo da análise. Antes de
consultas externas, e-mails, CPFs e telefones reconhecidos são mascarados na alegação de busca
e no prompt enviado à IA. Os campos narrativos derivados são mascarados antes de serem gravados;
a API repete essa proteção ao devolver resultados antigos. UUIDs, hashes, versões, datas e demais
metadados estruturais são preservados. Links de fontes que contenham esses dados
são omitidos para não apontarem a um endereço adulterado. A migração
`analysis.0002_mask_legacy_analysis_data` limpa os registros anteriores ao executar
`manage.py migrate`. A migração `analysis.0003_restore_technical_metadata` repara cópias de hashes
e versões que tenham sido mascaradas em `technical`, usando as colunas originais da análise.
Textos e URLs já removidos não são reconstruídos. O mascaramento é baseado em padrões e não detecta todos os dados pessoais;
o prazo de retenção e a revisão das cópias de segurança ainda precisam ser definidos.

### Exemplo de Requisição via Extensão (POST `/api/v1/analyses/`)

```json
{
  "input_type": "text",
  "title": "Título extraído da página",
  "subtitle": "Linha-fina ou og:description da página",
  "text": "Corpo principal do artigo extraído pelo content.js..."
}
```
```
Header: X-Client-Source: browser-extension
```

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
  "input_type": "text",
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
    "Foram encontradas expressões apelativas: "urgente", "milagrosa"."
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
    "aggregation": "first_window"
  },
  "risk": {
    "value": 88.5,
    "formula": "100 * sum(w_i * s_i) / sum(w_i)",
    "weights": {
      "model_fake_probability": 0.6,
      "linguistic_indicators": 0.15,
      "evidence_conflict": 0.25
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
    "code": "d972474"
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
npm test               # Executa os testes automatizados
npm run check          # Lint + typecheck + testes + build de produção
```
