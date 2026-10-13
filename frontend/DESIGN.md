# Apura Web — guia de design e rastreabilidade

Este documento responde a três perguntas sobre a interface web do Apura:

1. **Em que o design se apoia?** (fontes, ordem de precedência e autores de referência)
2. **Como o design está organizado?** (tokens, telas, componentes, camadas do código)
3. **O que dos requisitos v2.2 está atendido, o que depende do back end e o que não foi feito?**

Ele também registra as **decisões tomadas sem confirmação** e as **perguntas em aberto** (seção 9),
para que a equipe possa confirmá-las ou trocá-las.

> Nome do produto: **Apura**. O documento de requisitos, o protótipo e o repositório do back end
> ainda dizem "Fake Eyes"; o código desta interface não usa esse nome (um teste confere isso).

---

## 1. Fontes e ordem de precedência

Quando duas fontes discordam, vale a de cima.

| # | Fonte | O que define |
|---|-------|--------------|
| 1 | **Requisitos v2.2** (`Requisitos_Fake_Eyes_Revisados_v2_2.docx`) | O que a interface deve fazer. É a fonte da verdade. |
| 2 | **API v1 real** (neste repositório, `apura/analysis/`) | O que o back end faz hoje: endpoints, formato de resposta, códigos de erro. Onde a API não cobre um requisito, a interface não inventa; marca como dependência (seção 6). |
| 3 | **Arquitetura** (seção 10 do documento de arquitetura v6, ADR-006) | React + Vite, interface estática servida pelo nginx na mesma origem da API. |
| 4 | **Protótipo v2** (`fake-eyes-prototipo-v2.html`) | Identidade visual (azul-marinho e dourado, Roboto + STIX Two Text) e estrutura das telas. |
| 5 | **Convenções de design** de autores reconhecidos (seção 2) | Decisões de detalhe que as fontes acima não cobrem. |
| — | **Figma do projeto** | **Não foi consultado**: o Figma recusou o acesso (a conta usada aqui não tem acesso de edição ao arquivo). Ver seção 9. |

Os valores do protótipo que não atendiam ao RNF08 (WCAG 2.2 AA e alvos de 48 × 48 px) foram
**ajustados** e estão marcados com `AJUSTE` em `src/styles/tokens.css`. Exemplos: o dourado do
texto (3,8:1 → 5,1:1), o contorno dos campos (1,5:1 → 3,6:1) e o texto de apoio (4,2:1 → 5,5:1).

Também do protótipo, **não** foi mantido: o medidor circular de risco (substituído por uma escala
linear, seção 2) e a promessa "Referências rastreáveis" na tela inicial (trocada por "A decisão é
sua", antes da implementação da busca de fontes; o RF30 exige que o texto acompanhe o que o
sistema faz).

---

## 2. Princípios de design e onde foram aplicados

As convenções abaixo vêm de autores e padrões consagrados. A coluna "Onde" aponta a aplicação
concreta; não se trata de endosso dos autores, e sim de uma lista do que foi seguido, para que a
equipe possa discutir cada escolha.

| Princípio | Referência | Aplicação no Apura | Onde |
|-----------|------------|--------------------|------|
| Visibilidade do estado do sistema | Jakob Nielsen, *10 Usability Heuristics* | Ao enviar, a tela troca na hora para "Recebemos o seu conteúdo", com o tempo decorrido em texto e aviso quando a espera passa de 10 s. Nada de barra de progresso, que pareceria andamento real (RF25 proíbe progresso fictício). | `ProcessingPanel.jsx`, `state/analysisRun.jsx` |
| Prevenção e recuperação de erros | Nielsen; Luke Wroblewski, *Web Form Design* | Validação antes do envio, mensagem ligada ao campo, uma frase de problema e uma de saída, e um botão de ação em cada erro (RF27). O envio duplicado é ignorado enquanto há solicitação ativa. | `domain/validation.js`, `domain/errors.js`, `ErrorPanel.jsx` |
| Mensagem de erro junto do campo, em texto | GOV.UK Design System, componente *Error message*; WCAG 3.3.1 | O erro de entrada aparece colado ao campo, escrito (nunca só cor), ligado por `aria-describedby` e com `aria-invalid`; o foco vai para o campo. Erros sem campo (API indisponível, por exemplo) aparecem num painel que recebe o foco. | `Field.jsx`, `AnalysisForm.jsx`, `ErrorPanel.jsx` |
| Controle e liberdade do usuário; desfazer em vez de confirmar | Nielsen; Aza Raskin, *The Humane Interface* | "Cancelar" durante a análise. Excluir um item do histórico mostra "Desfazer" no aviso, sem janela de confirmação. Só "Limpar histórico", que apaga tudo, pede confirmação. | `HistoryPage.jsx`, `state/toast.jsx`, `ConfirmDialog.jsx` |
| Modelo conceitual claro; sinais visíveis | Don Norman, *The Design of Everyday Things* | O resultado segue sempre a mesma ordem: **status → o que fazer → por quê → fontes → indicadores → limitações → detalhes técnicos**. Cada controle parece o que é (botão, aba, campo). | `ResultPage.jsx`, `Button.jsx` |
| Não me faça pensar; hierarquia e escaneabilidade | Steve Krug, *Don't Make Me Think* | Uma ação principal por tela, títulos que dizem o que a seção contém, texto curto e em linguagem simples (RF16, RF17, RNF08). | todas as páginas |
| Clareza gráfica; pouca tinta decorativa | Edward Tufte, *The Visual Display of Quantitative Information* | O índice de risco é um número com escala, sem ornamento. | `RiskScale.jsx` |
| Escala linear com faixas (bullet graph) | Stephen Few, *Information Dashboard Design*; Cleveland & McGill (posição sobre escala comum é a codificação mais precisa) | O índice de 0 a 100 aparece numa barra com as três faixas do RF16 (até 25, até 60, acima de 60) e um marcador. Substitui o medidor circular do protótipo, que exige comparar ângulos. | `RiskScale.jsx`, `domain/status.js` |
| Escala tipográfica, medida e entrelinha | Robert Bringhurst, *The Elements of Typographic Style* | Escala com razão 1,25 sobre corpo de 17 px; linhas de 45 a 75 caracteres (`--measure: 65ch`); entrelinha do corpo ≥ 1,5. | `tokens.css`, `base.css` |
| Hierarquia e pareamento de fontes | Ellen Lupton, *Thinking with Type* | Roboto (interface) com STIX Two Text (títulos e marca): contraste entre o neutro funcional e a voz editorial. | `tokens.css` |
| Tamanho e distância dos alvos; poucas escolhas | Fitts; Hick–Hyman | Todo controle principal tem pelo menos 48 × 48 px (RNF08). Só duas abas de entrada e um botão principal por tela. | `--target-min`, `tokens.test.js` |
| Tokens em camadas | Brad Frost, *Atomic Design*; Nathan Curtis, *Naming Tokens in Design Systems* | Camada 1: primitivos (paleta, escalas). Camada 2: semânticos (o papel de cada valor). Os componentes só usam os semânticos. Um teste proíbe cor escrita à mão fora de `tokens.css`. | `tokens.css`, `tokens.test.js` |
| Tipografia fluida | Utopia (James Gilmore e Trys Mueller) | `--text-h1` e `--text-display` usam `clamp()` entre 320 e ~900 px, sem saltos. | `tokens.css` |
| Layout intrínseco | Andy Bell e Heydon Pickering, *Every Layout* | Grades com `minmax(0, 1fr)` (impedem que texto longo estoure a coluna) e linhas com `flex-wrap` e `flex-basis` mínimo, que quebram com fonte ampliada sem depender de largura de tela. | `layout.css`, `pages.css`, `components.css` |
| Postura da interface e público | Alan Cooper, *About Face* | Tratar a pessoa como inteligente e com pressa; não interromper o fluxo por detalhe. Pessoas idosas são o público de teste do RNF08. | tom dos textos; fluxo principal em 2 passos |
| Acessibilidade | WCAG 2.2 AA; WAI-ARIA Authoring Practices (APG) | Padrões APG para Tabs, Dialog modal (incluindo diálogo longo: foco inicial no título), Disclosure e Switch. Detalhes na seção 7. | `Tabs.jsx`, `Dialog.jsx`, `Disclosure.jsx`, `HistoryPage.jsx` |

---

## 3. Sistema de design

Tudo o que é visual está em **um arquivo**: `src/styles/tokens.css`. Os outros CSS só usam
`var(--…)`. Trocar a identidade visual (por exemplo, ao aplicar os valores do Figma) é editar
esse arquivo; `src/styles/tokens.test.js` (84 testes) confere contrastes, tamanhos e uso dos
tokens a cada alteração.

### 3.1 Camadas

```
1. Primitivos  →  --navy-900, --gold-500, --slate-600 …   (o que existe)
                  --text-body, --space-4, --radius-md …   (escalas)
2. Semânticos  →  --color-text, --color-surface, --color-primary, --color-focus-inner,
                  --tone-low-fg, --tone-attention-bg …    (para que serve)
Componentes    →  usam apenas a camada 2 (e as escalas)
```

### 3.2 Cores e contraste (WCAG 1.4.3 e 1.4.11)

Razões calculadas sobre os valores atuais de `tokens.css` (o teste exige ≥ 4,5:1 para texto e
≥ 3:1 para elementos de interface):

| Par | Razão | Mínimo |
|-----|-------|--------|
| Texto principal (`navy-900`) sobre o papel (`paper`) | 14,9:1 | 4,5 |
| Texto de apoio (`slate-600`) sobre o papel | 5,5:1 | 4,5 |
| Placeholder (`slate-500`) sobre branco | 5,3:1 | 4,5 |
| Texto dourado (`gold-800`) sobre o papel | 5,1:1 | 4,5 |
| Branco sobre azul-marinho | 16,2:1 | 4,5 |
| Texto de apoio (`ice-200`) sobre azul-marinho | 10,2:1 | 4,5 |
| Dourado claro (`gold-300`) sobre azul-marinho | 10,0:1 | 4,5 |
| Texto no botão dourado (`navy-900` sobre `gold-500`) | 6,6:1 | 4,5 |
| Texto no botão de perigo (branco sobre `red-700`) | 7,2:1 | 4,5 |
| Baixo risco (verde sobre verde-claro) | 6,2:1 | 4,5 |
| Requer atenção (âmbar sobre âmbar-claro) | 6,4:1 | 4,5 |
| Alto risco (vermelho sobre vermelho-claro) | 6,1:1 | 4,5 |
| Inconclusivo (aço sobre aço-claro) | 6,2:1 | 4,5 |
| Contorno de campo (`slate-400`) sobre branco / papel | 3,9:1 / 3,6:1 | 3 |

**A cor nunca é o único sinal** (WCAG 1.4.1): cada status do resultado tem **ícone com forma
própria** e **texto** ("Poucos sinais de risco", "Requer atenção", "Alto risco", "Análise
inconclusiva"), além da cor.

### 3.3 Tipografia

- Famílias: **Roboto** (interface e corpo) e **STIX Two Text** (títulos e marca), instaladas pelo
  `@fontsource` e **empacotadas** no site (sem chamada a serviço externo: privacidade e CSP).
  São as mesmas famílias que o protótipo embutia. O peso 500 destaca títulos e controles sem
  deixar a interface tão pesada quanto o peso 700.
- Escala: 12 · 15 · 16 · 17 · 18 · 21 · 26 · 33 · 41 px, mais
  dois tamanhos fluidos (`--text-h1`: 38 → 52 px; `--text-display`: 46 → 70 px).
- Tudo em `rem`: respeita o tamanho de fonte escolhido no navegador (WCAG 1.4.4). Nenhuma frase
  fica abaixo de 15 px; os 12 px são só para rótulos em caixa alta e negrito (um teste confere).
- Corpo de 17 px no computador e 16 px abaixo de 520 px. Entrelinha do corpo 1,6.
- Quebra de palavra: `overflow-wrap: break-word` no `body`. Não se usa `hyphens: auto` no corpo
  (a hifenização automática em português ainda erra), nem `overflow-wrap: anywhere` (que encolhe
  o tamanho mínimo de itens flex e quebrava palavras curtas).

### 3.4 Espaço, forma, profundidade e movimento

- Espaço em múltiplos de 4 px (`--space-1` … `--space-20`), conferido por teste.
- Raios `--radius-sm` … `--radius-xl` e `--radius-round`.
- Sombras: `--shadow-sheet` (cartões), `--shadow-raised`, `--shadow-toast`, `--shadow-dialog`.
- Movimento: `--duration-fast` (160 ms), `--duration-base` (250 ms), `--ease-out`. Com
  `prefers-reduced-motion: reduce` as animações e transições são desligadas (teste confere).

### 3.5 Foco (WCAG 2.4.7, 2.4.11, 2.4.13)

Anel de foco em **duas camadas**: dourada por dentro (2 px) e azul-marinho por fora (3 px, com
deslocamento de 2 px). A de dentro aparece sobre fundo escuro; a de fora, sobre fundo claro; juntas
passam de 3:1 sobre qualquer fundo do sistema. Nenhum CSS remove o contorno de controles (um teste
confere; só alvos programáticos com `tabindex="-1"` ficam sem anel).

### 3.6 Alvos de toque e clique (RNF08)

`--target-min: 3rem` (48 px com a fonte padrão). Vale para botões, links de navegação, abas,
campos, botões de ícone e links do rodapé e do aviso de demonstração. Verificado no navegador em
320, 768 e 1440 px.

### 3.7 Pontos de quebra e telas

Consultas de largura em **`em`** (não `px`), para que quem aumenta a fonte padrão do navegador
receba o layout compacto mais cedo. Equivalem a 312, 380, 520, 780, 1000 e 1500 px com a fonte de
16 px (um teste confere o conjunto). O conteúdo funciona de 320 a 1.440 px (RNF14) e além.

### 3.8 Preferências do sistema

| Preferência | Tratamento |
|-------------|------------|
| Fonte maior no navegador | Layouts quebram em vez de estourar (verificado em 150% e 200% com 360 px). |
| Menos movimento | Animações desligadas. |
| Cores forçadas (modo de alto contraste do Windows) | Bordas, foco e marcadores continuam visíveis (verificado com `forced-colors: active`). |
| Tema escuro | **Não implementado**: `color-scheme: light`. Não consta dos requisitos. |

---

## 4. Telas, rotas e componentes

### 4.1 Rotas (RF23)

| Rota | Tela | Requisitos |
|------|------|------------|
| `/` | Início: apresentação e formulário de análise | RF01, RF24, RF25, RF27, RF33 |
| `/resultado/:id` | Resultado da análise (o endereço é o identificador da análise) | RF16–RF19, RF26 |
| `/historico` | Histórico local | RF20, RF28 |
| `/como-funciona` | Finalidade, método, limitações e significado do índice | RF30 |
| `/privacidade` | Tratamento de dados, limite de visitante, feedback | RF30, RNF19 |
| `/entrar`, `/criar-conta`, `/recuperar-acesso`, `/conta` | Contas (**demonstração**) | RF31, RF32, RF34 |
| `*` | Página não encontrada, com caminho de volta | RF23 |

As rotas de conta só existem quando `VITE_ACCOUNTS_MODE=demo`. O roteador usa endereços sem `#`;
o servidor precisa devolver `index.html` para qualquer caminho (já feito em `deploy/nginx.conf`).

### 4.2 Componentes (`src/components/`)

| Pasta | Componentes |
|-------|-------------|
| `ui/` | `Button`, `Field`, `Tabs`, `Dialog`, `ConfirmDialog`, `Disclosure`, `Notice`, `StatusBadge`, `ToastRegion`, `Icon` |
| `layout/` | `Layout`, `Header` (menu móvel), `Footer`, `Brand`, `PageHeading`, `DemoBanner`, `ErrorBoundary` |
| `analysis/` | `AnalysisForm`, `AnalysisAside`, `UsageMeter`, `ProcessingPanel`, `ErrorPanel`, `LimitDialog` |
| `result/` | `VerdictCard`, `RiskScale`, `NextSteps`, `ExplanationSection`, `SourcesSection`, `IndicatorsSection`, `LimitationsSection`, `TechnicalDetails`, `ShareSummary`, `FeedbackPanel` |
| `history/` | `HistoryRow` |
| `account/` | `MigrateHistoryDialog` |
| `content/` | `Blocks` (renderiza os textos de "Como funciona" e "Privacidade") |

### 4.3 Camadas do código

```
src/domain/      regras puras, sem React: limites, validação, status e faixas, erros (RF27),
                 modelo da análise, resumo copiável, histórico, limite de visitante
src/services/    http (prazo de 30 s, cancelamento), API v1, armazenamento do navegador,
                 identificador anônimo, "gateways" de conta e feedback (hoje: demonstração)
src/state/       estado da análise em andamento, serviços, avisos
src/hooks/       ligação entre estado e componentes
src/components/  peças visuais          src/pages/  telas          src/content/  textos longos
```

Regras que os testes de higiene (`src/hygiene.test.js`) impõem:

- só `services/http.js` faz chamadas de rede; só `services/storage.js` toca o armazenamento do
  navegador; só `src/config.js` lê variáveis de ambiente;
- nada de `innerHTML`, `dangerouslySetInnerHTML`, `eval`, `javascript:`, `document.cookie`,
  `console.*`; `target="_blank"` sempre com `rel="noopener noreferrer"`;
- nenhum segredo no pacote (padrões de chaves conhecidas) e nenhuma variável `VITE_*` com nome de
  chave, senha ou token;
- nenhum `maxlength` nos campos (o texto longo não é cortado em silêncio, RF01);
- nenhum "Fake Eyes" no código, no HTML, no manifesto ou no `package.json`;
- CSS sem `url()` externo nem `@import`; HTML sem script ou estilo embutido.

A dependência vai sempre para dentro (`pages → components → hooks → state → services → domain`).
Há uma exceção pequena e conhecida: `state/toast.jsx` importa o `ToastRegion`, que ele mesmo
alimenta.

---

## 5. Contrato com o back end

API v1 (`apura/analysis/api/`):

| Chamada | Uso na interface |
|---------|------------------|
| `POST /api/v1/analyses/` com `input_type` e `text` (ou `url`), cabeçalho `X-Visitor-Id` | Envio. Resposta `201` síncrona com o resultado. |
| `GET /api/v1/analyses/{id}/` | Reabrir um resultado (link do histórico, recarregar a página, "Tentar de novo"). |
| `GET /api/v1/health/` | Disponibilidade (cliente pronto; sem uso em tela hoje). |

Erros chegam como `{"error": {"code", "message", "action", "field", "details"}}`. A interface
decide pelo **`code`** (estável), não pela mensagem. Se a resposta não bater com o contrato que
esta versão conhece, a leitura falha com o cenário `incompatible_api` em vez de exibir um
resultado errado (RF29: compatibilidade entre versões; versão aceita: `v1`).

O back end já emite `invalid_url` e códigos de URL como `forbidden_url`,
`dns_resolution_failed`, `url_timeout`, `network_error`, `paywall_or_forbidden`, `http_error`,
`non_text_content` e `empty_scraped_text`. A interface ainda propõe nomes diferentes para parte
desses cenários (`page_unreachable`, `page_blocked`, `page_paywalled`, `page_not_text`) em
`src/domain/errors.js`. `evidence_unavailable` não é emitido: a busca sem resposta é tratada como
lista vazia. Esse contrato de erro precisa de alinhamento próprio.

---

## 6. Rastreabilidade com os requisitos v2.2

Situações:

- **Atende**: a interface cumpre o requisito com a API de hoje.
- **Pronto na interface; depende do back end**: a tela está feita e testada com dados simulados;
  só funciona de verdade quando a API fornecer o dado.
- **Demonstração**: fluxo simulado no navegador, com aviso visível; nada é enviado nem guardado
  num servidor.
- **Parcial**: parte do critério de aceite não é cumprida (explicado na linha).
- **Não implementado**.
- **Fora da interface**: pertence ao back end, ao modelo ou à operação.

Os testes citados rodam com `npm test`.

### 6.1 Requisitos funcionais

| Req. | Prior. | Situação | Onde | Teste / evidência | Observações |
|------|--------|----------|------|-------------------|-------------|
| RF01 Entrada por texto ou URL | MVP | **Atende** (integração disponível) | `domain/validation.js`, `domain/text.js`, `AnalysisForm.jsx` | `validation.test.js`, `text.test.js`, `AnalysisForm.test.jsx` | 50 a 20.000 caracteres depois de normalizar; sem `maxlength`, então nada é cortado em silêncio. URL: só `http`/`https`, até 2.048 caracteres. A API v1 aceita texto e URL. |
| RF02 Extração estruturada | MVP | **Parcial** | `analysis/services/scraper.py` | Testes do back end com mocks | O back end extrai título, subtítulo, corpo, autoria, data e domínio, mas a resposta da API não expõe esses metadados separadamente; a interface não os mostra. |
| RF03 Falhas de URL | MVP | **Parcial** | `domain/errors.js`, `ErrorPanel.jsx` | `errors.test.js`, `ErrorPanel.test.jsx` | A API rejeita URL e falhas de extração com códigos próprios. Parte desses códigos ainda não está mapeada para o cenário específico da interface; ver seção 5. |
| RF04 Normalização e idioma | MVP | **Parcial** | `domain/text.js`, `domain/errors.js` | `text.test.js`, `errors.test.js` | A interface normaliza para contar e validar o tamanho. A detecção de idioma e de texto ilegível é do back end; a interface mostra a mensagem específica (`unsupported_language`, `text_unreadable`, `text_insufficient`) e não segue para o resultado. |
| RF05 Privacidade no processamento | MVP | **Parcial** | `services/resultCache.js`, `services/historyStore.js`, `content/privacy.js` | `stores.test.js`, `privacy.test.js`, `hygiene.test.js` | O rascunho fica só na memória e o histórico local guarda a alegação resumida. O servidor mascara CPF, e-mail e telefone nesse resumo, mas explicações e fontes persistidas podem repetir trechos do conteúdo; a página de privacidade informa essa limitação. |
| RF06 Alegação principal | MVP | **Parcial** | `VerdictCard.jsx` | `ResultPage.test.jsx` | A alegação aparece junto do resultado. **Confirmar, corrigir ou escolher outra alegação não foi implementado**: a API não tem esse contrato. A tela diz: "Ainda não é possível confirmar ou corrigir a alegação nesta versão." |
| RF07 Fontes relacionadas | MVP | **Parcial** | `SourcesSection.jsx`, `analysis/services/factcheck.py` | `ResultPage.test.jsx`; testes do back end com mocks | A API consulta a Google Fact Check Tools quando configurada e recorre a uma busca pública. A tela distingue ausência e fontes encontradas; o back end ainda não informa falha da consulta separadamente da ausência de resultados. |
| RF08 Relação fonte × alegação | MVP | **Parcial** | `SourcesSection.jsx`, `domain/analysis.js`, `analysis/services/factcheck.py` | `ResultPage.test.jsx`, `analysis.test.js` | A interface aceita relações compatível, conflitante, contextual e insuficiente. O back end gera as três primeiras por palavras do veredito ou do título/resumo, sem verificar em profundidade a correspondência com a alegação. Isso pode afetar o índice. |
| RF09 Contexto temporal e entidades | MVP | **Depende do back end** | — | — | A API v1 não devolve entidades nem indicador temporal; a interface não exibe nada do tipo (o RF09 manda mostrar o indicador só quando há relação explícita). |
| RF10 Indicadores linguísticos | MVP | **Atende** | `IndicatorsSection.jsx` | `ResultPage.test.jsx` | Rotulados como indicadores auxiliares, nunca como prova; seção separada das fontes. |
| RF11 Classificação textual | MVP | **Atende** (exibição) | `TechnicalDetails.jsx` | `ResultPage.test.jsx` | Mostra o identificador e a integridade (SHA-256) do modelo, a classe e a confiança, na área técnica. |
| RF12 Textos longos | MVP | **Atende** (exibição) | `VerdictCard.jsx`, `TechnicalDetails.jsx` | `ResultPage.test.jsx` | Quando o back end informa que o texto não foi analisado por inteiro, o resultado avisa "foram analisados X de Y trechos" e marca a análise como parcial; nada é apresentado como analisado sem ter sido. A divisão em trechos é do back end. |
| RF13 Índice de risco | MVP | **Atende** (exibição) | `RiskScale.jsx`, `TechnicalDetails.jsx`, `domain/format.js` | `status.test.js`, `format.test.js` | Descrito como "indicador de risco", nunca como probabilidade de falsidade. A área técnica mostra pesos, sinais usados, sinais ausentes e fórmula. O cálculo é do back end. |
| RF14 Incerteza e abstenção | MVP | **Atende** (exibição) | `VerdictCard.jsx`, `ExplanationSection.jsx` | `ResultPage.test.jsx`, `status.test.js` | O status inconclusivo tem prioridade, não mostra índice como conclusão e exibe a mensagem de cada motivo de abstenção que a API enviar. |
| RF15 Explicação dos sinais do modelo | Evolução | **Não implementado** | — | — | Prioridade "Evolução". |
| RF16 Resultado principal | MVP | **Atende** | `domain/status.js`, `VerdictCard.jsx`, `RiskScale.jsx`, `StatusBadge.jsx` | `status.test.js` | Faixas 0–25, acima de 25 até 60, acima de 60 até 100, sem lacunas (inteiros e decimais nos limites 25 e 60 testados). O inconclusivo prevalece. A porcentagem nunca é chamada de certeza. |
| RF17 Explicação e fontes | MVP | **Atende** | `ExplanationSection.jsx`, `SourcesSection.jsx`, `IndicatorsSection.jsx`, `LimitationsSection.jsx` | `ResultPage.test.jsx` | Quatro blocos separados: o que veio de fonte, o que foi detectado no texto, o que o modelo indicou e as limitações. A área técnica fica fechada por padrão. |
| RF18 Orientação e compartilhamento | MVP | **Atende** | `NextSteps.jsx`, `ShareSummary.jsx`, `domain/share.js` | `share.test.js`, `ResultPage.test.jsx` | O resumo copiável traz status, alegação, data, limitações e links; não afirma verificação humana; análise inconclusiva sai como "sem conclusão". |
| RF19 Feedback da análise | MVP | **Demonstração** | `FeedbackPanel.jsx`, `services/gateways.js` | `ResultPage.test.jsx`, `privacy.test.js` | Avaliação útil / não útil e comentário opcional, com a finalidade informada antes do envio. Hoje o envio é simulado: o back end não tem o endpoint (Etapa 4). |
| RF20 Histórico e exclusão | MVP | **Atende** (local). Sincronizado por conta: **demonstração** | `HistoryPage.jsx`, `HistoryRow.jsx`, `services/historyStore.js`, `domain/history.js` | `HistoryPage.test.jsx`, `history.test.js`, `stores.test.js` | Item: alegação resumida, status, data e identificador; nunca o texto integral. Excluir tira o item na hora (com "Desfazer"); "Limpar histórico" pede confirmação. |
| RF21 Versionamento | MVP | **Atende** (exibição) | `TechnicalDetails.jsx` | `ResultPage.test.jsx` | Mostra modelo, regras, calibrador, esquema e código usados em cada análise. A recuperação das versões é do back end. |
| RF22 Atualização do modelo | Evolução | **Fora da interface** | — | — | — |
| RF23 Estrutura e navegação | MVP | **Atende** | `Header.jsx`, `Footer.jsx`, `App.jsx` | `App.test.jsx` | Início, análise, resultado, histórico, "Como funciona" e privacidade a um clique, em celular e computador, sem depender do botão Voltar. |
| RF24 Formulário de análise | MVP | **Atende** | `AnalysisForm.jsx`, `Tabs.jsx` | `AnalysisForm.test.jsx` | Abas "Colar texto" e "Inserir link" (padrão APG), instruções, contador, validação ligada ao campo; só a opção selecionada vai na solicitação. |
| RF25 Estados de processamento | MVP | **Parcial** | `ProcessingPanel.jsx`, `state/analysisRun.jsx` | `ProcessingPanel.test.jsx`, `analysisRun.test.jsx` | Confirma o recebimento, mostra validação concluída e análise em andamento, o tempo decorrido contra o prazo de 30 s e permite cancelar; ignora envio duplicado. **"Extração da página" e "consulta a fontes" não aparecem** porque a API v1 é síncrona e não informa etapas; mostrá-las seria progresso fictício. Precisa de um endpoint de acompanhamento. |
| RF26 Apresentação do resultado | MVP | **Atende** | `ResultPage.jsx` | `ResultPage.test.jsx` | Resultado principal antes dos detalhes técnicos; "Nova verificação" visível no alto da página; cada fonte tem o botão "Abrir a fonte" (nova aba, com `rel="noopener noreferrer"`). |
| RF27 Tratamento de erros | MVP | **Parcial** | `domain/errors.js`, `ErrorPanel.jsx` | `errors.test.js`, `ErrorPanel.test.jsx` | Há telas para URL inválida, página inacessível, texto insuficiente, idioma não suportado, API indisponível, falha da consulta de evidências e tempo limite. Parte dos códigos reais de URL não está mapeada e o back end não distingue falha de evidências de ausência de resultados. |
| RF28 Interface do histórico | MVP | **Atende** (local). Conta em outro aparelho: **demonstração** | `HistoryPage.jsx`, `MigrateHistoryDialog.jsx` | `HistoryPage.test.jsx`, `AuthPage.test.jsx` | Os itens locais permanecem depois de fechar o navegador. O histórico local só é vinculado à conta depois de confirmação explícita. A sincronização entre aparelhos precisa do back end. |
| RF29 Integração com a API | MVP | **Atende** | `services/analysesApi.js`, `services/http.js`, `domain/analysis.js` | `analysesApi.test.js`, `http.test.js`, `analysis.test.js`, `analysisRun.test.jsx` | Testes de sucesso, análise inconclusiva, erro de validação, indisponibilidade (rede, 502, 503), tempo limite e versão incompatível. Não há teste contra a API real em CI (seção 11). |
| RF30 Informações e privacidade | MVP | **Parcial** (textos alinhados ao fluxo atual; revisão jurídica pendente) | `content/how.js`, `content/privacy.js`, `HowPage.jsx`, `PrivacyPage.jsx` | `how.test.js`, `privacy.test.js` | Os textos informam que link e fontes existem e descrevem a possível síntese por IA externa. Contas e feedback continuam em demonstração. Os textos ainda dependem de revisão jurídica e da correção das limitações de correspondência entre fonte e alegação. |
| RF31 Cadastro, login e logout | MVP | **Demonstração** | `AuthPage.jsx`, `AccountPage.jsx`, `domain/auth.js` | `AuthPage.test.jsx`, `AccountPage.test.jsx`, `auth.test.js` | Pede só e-mail, senha e aceite da privacidade. A demonstração não guarda e-mail nem senha. Mensagem de falha de login não revela se a conta existe. Autenticação real é da Etapa 4. |
| RF32 Recuperação e sessões | MVP | **Demonstração** | `RecoveryPage.jsx` | `RecoveryPage.test.jsx` | Fluxo de pedido de recuperação; o código ou link de uso único é do back end. |
| RF33 Limite de visitante | MVP | **Parcial** | `domain/visitorLimit.js`, `services/visitorLimitStore.js`, `LimitDialog.jsx`, `UsageMeter.jsx` | `visitorLimit.test.js`, `analysisRun.test.jsx`, `stores.test.js` | Três análises em 24 h a partir da primeira contabilizada; texto e link no mesmo contador; só resultado ou análise inconclusiva consome; recusa por validação e falha técnica não consomem; a quarta não inicia e mostra cadastro, login e o tempo restante. **O contador existe só no navegador** (limpar o armazenamento o reinicia, risco conhecido do RNF19); o contador no servidor é da Etapa 4. |
| RF34 Exclusão de conta | MVP | **Demonstração** | `AccountPage.jsx` | `AccountPage.test.jsx` | Explica o efeito antes da confirmação. A exclusão real é do back end. |
| RF35 Contestação | Evolução | **Não implementado** | — | — | Prioridade "Evolução". |

### 6.2 Requisitos não funcionais

| Req. | Prior. | Situação | Onde / evidência | Observações |
|------|--------|----------|------------------|-------------|
| RNF01 Desempenho (30 s) | MVP | **Atende** na interface | `services/http.js` (cancela a requisição aos 30 s e mostra o erro "tempo limite"); `http.test.js`, `analysisRun.test.jsx` | A medição de p50, p95 e p99 exigida pelo critério de aceite é do back end e **não foi feita**. O nginx espera 35 s, mais que os 30 s da interface (ver "Implantação" no README). |
| RNF02, RNF03, RNF04, RNF05, RNF06, RNF07, RNF09, RNF12 | — | **Fora da interface** | — | Disponibilidade, qualidade e calibração do modelo, reprodutibilidade, monitoramento, segurança da consulta de URL e capacidade. Na interface, o RNF09 aparece só como validação de `http`/`https` e como exibição de links apenas `http(s)`. |
| RNF08 Acessibilidade | MVP | **Parcial** | `tokens.test.js`, `eslint-plugin-jsx-a11y`, `vitest-axe` nos testes de página, auditoria no navegador (seção 7) | Automático e verificações no navegador: feitos. **Faltam** os testes manuais com leitor de tela real e a validação com pessoas idosas, que o critério de aceite exige. |
| RNF10 Privacidade e retenção | MVP | **Atende** (lado da interface) | `services/storage.js`, `content/privacy.js` | A interface não registra texto nem dados pessoais (sem `console.*`, sem telemetria). Prazo de guarda no servidor: **a definir pela equipe** (a página de privacidade diz isso). Comentário de feedback: prazo de 30 dias descrito quando o feedback for real. |
| RNF11 Arquitetura | MVP | **Atende** | Seção 4.3; contratos em JSDoc verificados por `tsc` (`npm run typecheck`) | Interface separada da API por um contrato HTTP; nenhuma ferramenta de implantação é exigida (Docker é opcional). |
| RNF13 Testes | MVP | **Parcial** | Testes automatizados; `npm run check` (lint + tipos + testes + build) | Falta configurar a **integração contínua** que impede a publicação em caso de falha; o comando já existe. |
| RNF14 Responsividade | MVP | **Atende** | Verificado no navegador: 29 larguras (320 a 1.440 px) × 9 rotas, sem rolagem horizontal; fonte padrão ampliada a 150% e 200% | Sem sobreposição, corte ou perda de função nas telas medidas. |
| RNF15 Compatibilidade | MVP | **Não verificado** | — | Só foi testado em **Chromium**. A matriz de compatibilidade (Chrome, Edge, Firefox e Safari, duas versões) **não foi preenchida**. O CSS e o JavaScript usam recursos disponíveis nesses navegadores, mas isso não substitui o teste. |
| RNF16 Segurança da aplicação web | MVP | **Atende** (lado da interface) | `deploy/security-headers.conf`, `hygiene.test.js` | CSP restritiva (sem script nem estilo embutido, `connect-src 'self'`), React escapa texto, links validados, sem segredo no pacote. Verificado no navegador com a CSP aplicada: zero erros no console em todas as telas e fluxos. **HTTPS, CORS e limite de requisições** dependem da implantação e do back end. |
| RNF17 Resposta percebida | MVP | **Atende** | `ProcessingPanel.jsx`, `analysisRun.test.jsx` | O estado "analisando" aparece no mesmo clique; o tempo decorrido atualiza a cada segundo; ao fim de 30 s a tela recebe um erro controlado. |
| RNF18 Autenticação e sessão | MVP | **Demonstração** | — | Depende de cookie de sessão e proteções do back end (Etapa 4). Por isso a ADR-006 prevê a mesma origem (cookie `SameSite=Lax`). |
| RNF19 Privacidade do limite | MVP | **Atende** (lado da interface) | `services/visitor.js`, `content/privacy.js` | Identificador aleatório gerado no navegador, sem impressão digital do aparelho, enviado em `X-Visitor-Id`; a página de privacidade informa finalidade, janela de 24 h e limitações. O registro mínimo no servidor é do back end. |

### 6.3 Critérios gerais de conclusão do MVP (seção 4 dos requisitos)

| Critério | Situação |
|----------|----------|
| O resultado distingue índice de risco, indicadores do modelo e evidências externas | Atende (RF17). |
| A análise inconclusiva sai sem forçar classificação | Atende (RF14, RF16). |
| Testes de acessibilidade concluídos | Parcial (RNF08: faltam leitor de tela e pessoas idosas). |
| Cadastro, login, recuperação, logout e exclusão de conta aprovados em testes funcionais e de segurança | Não aplicável ainda: demonstração. |
| Limite de três análises sem afetar solicitações inválidas ou falhas técnicas | Atende no navegador (RF33); falta o contador no servidor. |
| Fluxo web aprovado nos navegadores e tamanhos definidos | Parcial: tamanhos sim; navegadores não (RNF15). |

---

## 7. Acessibilidade (RNF08, WCAG 2.2 AA)

| Critério WCAG | Como é atendido |
|---------------|-----------------|
| 1.1.1 Conteúdo não textual | Ícones decorativos com `aria-hidden`; ícones com significado têm texto ao lado. |
| 1.3.1, 4.1.2 Estrutura e papéis | HTML semântico (`header`, `nav`, `main`, `footer`, `h1`–`h3`, listas, `dl`); abas, janelas e interruptor seguem o padrão APG. |
| 1.4.1 Uso de cor | Status = cor + ícone + texto. |
| 1.4.3, 1.4.11 Contraste | Seção 3.2, conferido por teste. |
| 1.4.4 Redimensionar texto; 1.4.10 Reflow; 1.4.12 Espaçamento | Fontes em `rem`; pontos de quebra em `em`; verificado a 200% em 360 px sem rolagem horizontal. |
| 2.1.1 Teclado; 2.1.2 Sem armadilha | Todo fluxo funciona só com teclado; janelas usam `<dialog>` nativo (foco preso dentro enquanto aberta) e devolvem o foco ao fechar. |
| 2.4.1 Pular blocos | Link "Ir para o conteúdo". |
| 2.4.2 Título da página | Cada rota atualiza o `<title>`. |
| 2.4.3 Ordem do foco | Ao trocar de tela ou de estado, o foco vai para o título ou para o erro; no diálogo mais alto que a janela, o foco inicial vai para o título (APG). |
| 2.4.7, 2.4.11, 2.4.13 Foco visível | Seção 3.5. |
| 2.5.8 Tamanho do alvo | 48 × 48 px (acima dos 24 px do AA). |
| 3.2.x Previsibilidade | Navegação igual em todas as telas; nenhuma mudança de contexto sem ação da pessoa. |
| 3.3.1–3.3.3 Erros | Mensagem ligada ao campo, com instrução de correção. |
| 4.1.3 Mensagens de estado | Avisos (toasts) em duas regiões `aria-live` (educada e assertiva); o painel de processamento, o carregamento do resultado e as confirmações usam `role="status"`. |

**Como foi verificado**

- Automático, a cada `npm test`: `eslint-plugin-jsx-a11y`, `vitest-axe` nas páginas e componentes
  principais e os testes de tokens.
- No navegador (Chromium sem tela, com axe-core): 0 violações em 320, 768 e 1440 px; alvos ≥ 48 px;
  sem rolagem horizontal; 33 fluxos (envio, erros, limite, histórico, contas, menu móvel); foco,
  menu móvel, aviso com "Desfazer", movimento reduzido, cores forçadas e fonte ampliada. Tudo isso
  também com a CSP real aplicada. Esses roteiros foram executados fora do repositório e **não**
  fazem parte de `npm run check`.
- **Não feito**: leitor de tela real (NVDA, JAWS, VoiceOver, TalkBack) e validação com pessoas
  idosas, exigidos pelo critério de aceite do RNF08.

---

## 8. Privacidade e segurança na interface

**O que o navegador guarda** (`localStorage`, prefixo `apura:`; tudo legível por scripts da própria
página, nada é segredo):

| Chave | Conteúdo |
|-------|----------|
| `apura:visitor-id` | Identificador aleatório (UUID), criado só quando a primeira análise é enviada. |
| `apura:visitor-limit` | Início da janela de 24 h e contagem. |
| `apura:history:v1` | Itens do histórico: identificador, alegação resumida, status, data, tipo de entrada. |
| `apura:history-enabled` | Se o histórico local está ligado (padrão: ligado, com chave para desligar). |
| `apura:demo-session` | Só "entrou: sim/não" e "histórico vinculado: sim/não" (demonstração). Sem e-mail nem senha. |

Se o armazenamento não estiver disponível (janela privada, cota cheia), a interface continua
funcionando com memória da página.

**O que nunca é guardado no navegador:** o texto analisado, e-mail, senha, resultados completos (o
cache de resultados fica na memória e some ao recarregar; o resultado é buscado de novo na API).

**Segurança:**

- CSP: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`.
  Além de `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy` e `Cross-Origin-Resource-Policy` (`deploy/security-headers.conf`).
- Sem fontes, scripts ou imagens de terceiros.
- Mesma origem para a interface e a API (ADR-006): sem CORS e com cookie de sessão `SameSite=Lax`.
  Se a API ficar em outra origem, é preciso liberar `X-Visitor-Id` no CORS do back end e acrescentar
  a origem a `connect-src`.
- Nenhum segredo em variável `VITE_*` (tudo isso vai para o navegador).
- Os resultados da API recebem `Cache-Control: no-store` no nginx.

---

## 9. Decisões tomadas sem confirmação e perguntas em aberto

A instrução do projeto é "siga os requisitos fielmente, não invente nada, pergunte as dúvidas".
Para não parar o trabalho, as dúvidas abaixo foram resolvidas com a leitura mais conservadora. **Cada
uma pode ser trocada**; indico onde.

### 9.1 Decisões

| # | Decisão | Motivo | Para trocar |
|---|---------|--------|-------------|
| 1 | Base visual: **protótipo v2 (HTML)**, e não o `apura-front 2.zip` | O zip tinha outra identidade e usava a rota antiga `POST /analisar`, que não existe na API v1. | `tokens.css` |
| 2 | **Figma não consultado** | Acesso recusado pelo Figma. | Dar acesso ao arquivo ou exportar cores e fontes; ajustar `tokens.css`. |
| 3 | Vite + nginx na mesma origem tratados como confirmados | ADR-006 estava "proposta, a confirmar". | `deploy/`, `VITE_API_BASE_URL` |
| 4 | **Aba "Inserir link" ligada** por padrão | O RF24 manda oferecer texto e URL; a API v1 já processa links. | `VITE_FEATURE_URL_INPUT=false` mostra a aba como "Em breve". |
| 5 | Cadastro pede **só e-mail, senha e aceite da privacidade** | RF31: "apenas os dados necessários". O protótipo pedia também o nome. | `AuthPage.jsx` |
| 6 | Histórico local **ligado por padrão**, com chave para desligar | RF20 diz "opcional". | `services/historyStore.js` |
| 7 | Contas e feedback em **demonstração**, com aviso visível | O back end não tem esses endpoints (Etapa 4). | `VITE_ACCOUNTS_MODE`, `VITE_FEEDBACK_MODE`; trocar o gateway em `services/index.js`. |
| 8 | Limite de visitante só no navegador | Contador no servidor é da Etapa 4. | `services/visitorLimitStore.js` |
| 9 | Teto técnico de **100 itens** no histórico | `localStorage` tem cota; não vem dos requisitos. | `domain/limits.js` |
| 10 | O campo de texto **não tem `maxlength`** | RF01: "sem corte silencioso". Passou do limite, o contador avisa e o envio fica bloqueado. | — |
| 11 | **Sem progresso fictício** | RF25. As etapas "extração" e "consulta a fontes" só entram quando existir endpoint de acompanhamento. | `ProcessingPanel.jsx` |
| 12 | Escala linear de risco no lugar do medidor circular | Seção 2 (Few; Cleveland & McGill). | `RiskScale.jsx` |
| 13 | Promessa "Referências rastreáveis" trocada por "A decisão é sua" | A relação entre cada fonte e a alegação ainda é heurística. | `HomePage.jsx` |
| 14 | Botão "Usar texto de exemplo" mantido; **conta no limite do visitante** | Veio do protótipo; é uma análise de verdade. | `AnalysisForm.jsx` |
| 15 | Índice exibido com até 2 casas decimais; pesos e sinais na área técnica também | Não esconder o valor que a API calcula. | `domain/format.js` |
| 16 | Falha de evidência: "Tentar de novo" faz `GET /analyses/{id}/` | A consulta lê o resultado persistido; ela não refaz a busca externa. | `ResultPage.jsx` |
| 17 | Aviso "Desfazer" fica no fim da ordem de tabulação | Documentado como trade-off; o aviso é operável por teclado e pausa ao receber foco ou mouse. | `ToastRegion.jsx` |
| 18 | Texto de privacidade escrito **só** com o que o código faz; prazo de retenção "a definir pela equipe" | RF30 e RNF10. Precisa de revisão jurídica. | `content/privacy.js` |
| 19 | Node 22.12 ou 24 | Exigência do Vite 8. | `package.json` (`engines`) |

### 9.2 Perguntas em aberto (para a equipe)

1. **Figma:** dar acesso ao arquivo (ou exportar cores e fontes) para conferir a identidade visual?
2. **Contrato com o back end:** alinhar os códigos de falha de URL (seção 5) e decidir se a API
   deve expor os metadados extraídos da página (RF02), entidades (RF09) e falhas da busca (RF07).
3. **RF25:** haverá um endpoint de acompanhamento com as etapas reais?
4. **RF06:** como a pessoa confirma ou corrige a alegação (contrato da API)?
5. **Etapa 4:** contratos de conta, recuperação, exclusão, histórico sincronizado e feedback.
6. **Privacidade:** prazo de guarda dos registros técnicos, base legal e canal de contato. O termo
   "identificador anônimo" é o do RNF19, mas juridicamente o identificador é **pseudonimizado**;
   convém o jurídico decidir a redação.
7. **Histórico local:** ligado por padrão está bem, ou deve começar desligado?
8. **Cadastro:** o nome é necessário? (Hoje não é pedido.)

---

## 10. Limitações e riscos conhecidos

- **Docker e nginx não foram executados** no ambiente de desenvolvimento (não havia daemon nem
  binário). `deploy/nginx.conf` foi só validado sintaticamente; a CSP foi testada de verdade no
  navegador, servida por um servidor com os mesmos cabeçalhos. Rode `nginx -t` antes de publicar.
- **Só Chromium** foi usado nos testes de navegador (RNF15 pendente).
- **Leitor de tela e pessoas idosas** não participaram (RNF08 pendente).
- **Contador de visitante no navegador:** limpar os dados do navegador o reinicia (risco do RNF19).
- **Relação entre fonte e alegação heurística:** títulos e vereditos podem indicar uma relação
  incorreta; o índice de risco usa essa classificação quando há fonte compatível ou conflitante.
- **Endereços que não existem** recebem HTTP 200 com a tela "Página não encontrada" (o servidor
  devolve `index.html` para qualquer caminho): é o comportamento padrão de uma aplicação de página
  única. Não afeta o uso; só muda como ferramentas externas (buscadores, monitoramento) enxergam
  endereços inexistentes.
- **Aviso "Desfazer"** no fim da ordem de tabulação (decisão 17).

---

## 11. Como verificar

```bash
npm ci
npm run check        # eslint + tsc + vitest + build de produção
npm run dev          # servidor de desenvolvimento (proxy de /api para DEV_API_PROXY_TARGET)
```

`npm run check` deve terminar sem erro. Falta ligar esse comando à integração contínua (RNF13) e
acrescentar:

- um teste de ponta a ponta contra o back end real (Playwright, por exemplo);
- a matriz de navegadores (RNF15);
- os testes manuais de acessibilidade (RNF08).
