# Apura Web

Interface web do **Apura**, sistema de apoio à avaliação de notícias e alegações em português.
A pessoa cola um texto, recebe um **indicador de risco**, a explicação dos sinais, as limitações e os
próximos passos. O Apura **não diz se algo é verdadeiro ou falso**: a decisão final é de quem lê.

- React 19 + Vite 8 + React Router 7, em JavaScript com tipos verificados por JSDoc (`tsc`).
- Sem biblioteca de componentes: CSS próprio, com tokens de design em `src/styles/tokens.css`.
- Consome a API v1 do back end (`verificAI`, Django + DRF).
- Segue os **Requisitos v2.2**. A rastreabilidade (o que atende, o que depende do back end e o que
  falta) e as decisões de design estão em [`DESIGN.md`](DESIGN.md).

> O documento de requisitos e o repositório do back end ainda usam o nome "Fake Eyes". O nome
> decidido é **Apura**.

## Requisitos

- Node.js **22.12 ou superior** (ou 24). O Vite 8 não roda em versões menores.
- O back end rodando (veja "Como rodar com o back end").

## Início rápido

```bash
npm ci
cp .env.example .env      # opcional: os padrões já servem para desenvolver
npm run dev               # http://localhost:5173
```

O servidor de desenvolvimento repassa `/api` para o Django (o mesmo desenho de produção, em que
interface e API ficam na mesma origem). Por padrão o destino é `http://localhost:8000`. Para outro
endereço, defina `DEV_API_PROXY_TARGET` no `.env`:

```bash
DEV_API_PROXY_TARGET=http://localhost:8000
```

### Como rodar com o back end

No repositório do back end (`verificAI`), suba a API. Com o Docker:

```bash
docker compose up db web
```

Isso expõe o Django só dentro da rede do Compose (`expose: 8000`). Para usá-lo a partir do
`npm run dev`, publique a porta (por exemplo, `ports: ["8000:8000"]` no serviço `web`, num arquivo de
override) ou rode o Django direto no seu computador (`python manage.py runserver`, dentro da pasta `apura/`,
como descreve o README do back end).

Sem o back end, a interface abre normalmente, mas a análise mostra o erro "serviço indisponível".

## Variáveis de ambiente

O Vite só entrega ao navegador as que começam com `VITE_`. **Tudo o que começa com `VITE_` fica
visível para quem abrir o site: nunca coloque chaves, tokens ou senhas aqui** (RNF16; um teste
falha se aparecer algo com cara de segredo).

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `VITE_API_BASE_URL` | `/api` | Endereço base da API. Padrão: mesma origem. Se a API ficar em outra origem, o back end precisa liberar o cabeçalho `X-Visitor-Id` no CORS e a origem entra em `connect-src` (`deploy/security-headers.conf`). |
| `VITE_REQUEST_TIMEOUT_MS` | `30000` | Prazo máximo de espera de uma análise (RNF01: 30 s). |
| `VITE_FEATURE_URL_INPUT` | `true` | `true`: a aba "Inserir link" envia a URL à API. `false`: a aba aparece como "Em breve". |
| `VITE_ACCOUNTS_MODE` | `demo` | `demo`: cadastro, login, recuperação e exclusão de conta em **demonstração**, com aviso visível. `off`: recursos de conta ocultos. |
| `VITE_FEEDBACK_MODE` | `demo` | `demo`: avaliação da análise em demonstração. `off`: oculta. |
| `VITE_BACKEND_URL_ANALYSIS` | `true` | Só muda os textos de "Como funciona" e "Privacidade". Use `false` com uma API anterior sem análise de links. |
| `VITE_BACKEND_SOURCES` | `true` | Só muda os mesmos textos. Use `false` com uma API anterior sem consulta a fontes. |
| `DEV_API_PROXY_TARGET` | `http://localhost:8000` | Destino do proxy de `npm run dev` e `npm run preview`. Não vai para o pacote. |

## Scripts

| Comando | O que faz |
|---------|-----------|
| `npm run dev` | Servidor de desenvolvimento. |
| `npm run build` | Gera o site estático em `dist/`. |
| `npm run preview` | Serve o `dist/` (com o mesmo proxy de `/api`). |
| `npm test` | Testes (Vitest + Testing Library + axe). |
| `npm run lint` | ESLint (inclui regras de acessibilidade, `jsx-a11y`). |
| `npm run typecheck` | Verifica os tipos de `src/domain`, `src/services` e `src/config.js` (JSDoc + `tsc`). |
| `npm run check` | Tudo acima, em sequência: lint, tipos, testes e build. **Use este na integração contínua.** |

## Estrutura

```
src/
  domain/       regras puras, sem React: limites, validação, status e faixas de risco, erros,
                modelo da análise, resumo copiável, histórico, limite de visitante
  services/     http (prazo de 30 s, cancelamento), API v1, armazenamento, identificador do
                visitante, "gateways" de conta e feedback (hoje em demonstração)
  state/        análise em andamento, serviços, avisos
  hooks/        ligação entre estado e componentes
  components/   ui/ (botão, campo, abas, diálogo…), layout/, analysis/, result/, history/, account/
  pages/        uma por rota
  content/      textos longos de "Como funciona" e "Privacidade"
  styles/       tokens.css (única fonte de valores visuais), base, layout, components, pages
  test/         utilitários de teste
deploy/         nginx.conf e security-headers.conf (CSP e demais cabeçalhos)
Dockerfile      build do site + nginx
DESIGN.md       guia de design e rastreabilidade com os requisitos
```

A pasta `src/domain` não importa React, e só `services/http.js` faz chamadas de rede. Os testes em
`src/hygiene.test.js` garantem essas regras (e proíbem `innerHTML`, `eval`, segredos no pacote,
`console.*` e o nome antigo do produto).

### Trocar a identidade visual

Todas as cores, fontes, tamanhos, espaços, raios e sombras estão em `src/styles/tokens.css`. Os
outros arquivos CSS não escrevem valores à mão (um teste confere). Para aplicar outros valores, edite
só esse arquivo e rode `npm test`: os testes de `src/styles/tokens.test.js` recusam combinações de
cor abaixo do contraste exigido pelo WCAG 2.2 AA e alvos menores que 48 px.

## Testes

```bash
npm test                              # tudo
npx vitest run src/domain             # só as regras
npx vitest run src/pages/ResultPage   # uma tela
npm run test:watch                    # modo contínuo
```

Os testes não dependem do back end: a API é simulada.

O que **não** está nos testes automáticos (veja `DESIGN.md`, seções 7 e 10):

- leitor de tela real e validação com pessoas idosas (RNF08);
- Firefox, Safari e Edge (RNF15; só se usou Chromium);
- teste de ponta a ponta contra o back end real.

## Implantação

O site é estático. Em produção, um nginx entrega a interface em `/` e repassa `/api/` ao Django:
**mesma origem**, sem CORS, e com o cookie de sessão `SameSite=Lax` das contas funcionando (ADR-006).

### Com Docker

```bash
docker build -t apura-web .
```

Para trocar uma variável `VITE_*` no pacote, use `--build-arg`:

```bash
docker build -t apura-web --build-arg VITE_ACCOUNTS_MODE=off --build-arg VITE_FEEDBACK_MODE=off .
```

### Junto do back end (docker compose)

O `docker-compose.yml` do `verificAI` tem um serviço `nginx` que apenas repassa tudo ao Django. Este
projeto traz um nginx que o **substitui**: serve a interface e repassa `/api/`, `/admin/` e `/static/`.
No `docker-compose.yml` do back end, troque o serviço `nginx` por (ajustando o `context` para a
pasta deste projeto):

```yaml
  nginx:
    build:
      context: ../apura-front
    container_name: apura_nginx
    restart: always
    ports:
      - "80:80"
    volumes:
      - static_volume:/code/apura/static:ro
    depends_on:
      - web
```

Note que o volume `./nginx:/etc/nginx/conf.d` **sai**: a configuração agora vem dentro da imagem
(`deploy/nginx.conf`).

### O que a configuração do nginx faz

- `/` serve o site; qualquer caminho desconhecido cai em `index.html` (o roteador do navegador
  decide a tela).
- `/assets/` (arquivos com hash no nome) fica um ano em cache; `index.html` é sempre revalidado.
- `/api/` vai para `web:8000`. A resposta recebe `Cache-Control: no-store`.
- **Prazos:** a interface espera 30 s (RNF01); o nginx espera **35 s** (`proxy_read_timeout`, como
  no nginx atual do back end), para a API responder o próprio erro antes de a conexão ser cortada.
  Confira o prazo do servidor da aplicação (o `gunicorn` do back end usa 60 s, maior que os dois).
- **Limite de requisições por IP:** o nginx repassa `X-Forwarded-For` como `$remote_addr` (e não
  `$proxy_add_x_forwarded_for`), para que um cliente não escolha o IP que o Django vê e contorne o
  limite. Se houver outro proxy ou balanceador na frente, configure o módulo `realip` em vez disto.
- **Cabeçalhos de segurança** (`deploy/security-headers.conf`): CSP restritiva, `nosniff`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `COOP` e `CORP`. Com HTTPS, ative a
  linha do `Strict-Transport-Security` indicada no arquivo.
- `/admin/` está liberado como no nginx do back end. **Se a administração não deve ficar pública,
  apague esse bloco.**

### Antes de publicar

1. **Rode `nginx -t`** com a configuração. Ela foi escrita e conferida, mas **não foi executada num
   nginx de verdade** (o ambiente de desenvolvimento não tinha Docker nem nginx). A política de
   conteúdo (CSP) foi testada em um navegador, servida por um servidor com os mesmos cabeçalhos.
2. No back end, confira `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` para o domínio de
   produção (o nginx repassa o `Host` original).
3. Ative HTTPS. A configuração de certificado fica no balanceador ou em um nginx à frente.
4. Revise os textos de privacidade (`src/content/privacy.js`) com o jurídico: prazo de guarda, base
   legal e canal de contato aparecem como "a definir pela equipe".

## Pendências conhecidas

Resumo; o detalhe, com os requisitos de cada item, está em `DESIGN.md`.

- **Já existe no back end:** análise por link e extração da página (Etapa 2), consulta a fontes
  e síntese explicativa (Etapa 3). A correspondência entre alegação e fonte ainda é heurística;
  confira cada referência antes de usá-la como evidência.
- **Depende do back end:** contas, histórico sincronizado, feedback e contador de visitante no
  servidor (Etapa 4), etapas reais de processamento (RF25), confirmação da alegação (RF06).
- **Demonstração (com aviso visível na tela):** cadastro, login, recuperação de acesso, exclusão de
  conta e envio de feedback.
- **Códigos de erro:** a API de URL usa, entre outros, `invalid_url`, `forbidden_url`,
  `dns_resolution_failed`, `url_timeout`, `network_error`, `paywall_or_forbidden`, `http_error`,
  `non_text_content` e `empty_scraped_text`. Alguns códigos previstos pela interface ainda não
  correspondem a esses nomes; alinhar o tratamento é uma pendência separada.
- **Não implementado:** RF15 (explicação por trechos) e RF35 (contestação), ambos de prioridade
  "Evolução".
- **Não verificado:** Figma do projeto (o acesso foi recusado), navegadores além do Chromium, leitor
  de tela real, Docker/nginx em execução.
