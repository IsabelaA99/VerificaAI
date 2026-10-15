# Apura no WhatsApp

Chatbot do Apura para o WhatsApp (Flask + Twilio), escrito na estrutura do RosaIA. A pessoa cola
o texto de uma notícia ou de uma mensagem recebida; o chatbot envia o texto à **API do Apura**
(`POST /api/v1/analyses/`) e responde com o status em linguagem simples, o índice de risco, a
explicação, as limitações e o que fazer agora.

O chatbot **não analisa nada sozinho**: não há modelo, nem Gemini, nem regra de risco aqui. Tudo
o que a resposta diz sobre a análise vem da API (fonte única), e o chatbot só organiza o texto.

> **Escopo.** O documento de requisitos v2.2 cobre a interface web e não menciona o WhatsApp.
> Por isso este chatbot **não tem requisitos próprios**: ele segue os que valem para qualquer
> canal (RF14, RF16, RF17, RF18, RF27, RNF01, RNF10) e as decisões abaixo, que o grupo precisa
> confirmar (seção "Decisões a confirmar").

## Estrutura

Mesmo desenho do RosaIA, trocando o que era do Gemini pelo que é do Apura:

| RosaIA | Apura | O que faz |
|---|---|---|
| `app.py` | `app.py` | Cria o Flask e registra o Blueprint (agora em `create_app()`, para testar e para o gunicorn) |
| `routes/messaging_routes.py` | `routes/messaging_routes.py` | `POST /mensagem` (webhook da Twilio, resposta em TwiML) e `GET /saude` (no lugar de `/test`) |
| `services/gemini_service.py` | `services/apura_client.py` | Fala com a API do Apura |
| `services/context.py` (prompt do Gemini) | `services/messages.py` | Textos que a pessoa lê |
| `services/knowledge_loader.py` | não existe | Não há base de conhecimento: quem sabe é a API |
| — | `services/reply_builder.py` | Monta a resposta (RF16 a RF18) a partir do resultado da API |
| — | `services/replies.py` | Decide o que responder e como lidar com o prazo da Twilio |
| — | `services/twilio_io.py` | Confere a assinatura da Twilio e envia mensagens |
| — | `services/safe_log.py` | Log sem texto nem telefone |
| `utils/message_utils.py` | `utils/message_utils.py` | `split_message` (corrigida) e leitura do que a pessoa enviou |
| `Procfile` | `Procfile` | gunicorn |
| — | `tools/` | Ferramentas para testar à mão, sem Twilio e sem o back end (não vão para produção) |

## Como uma mensagem é tratada

```
Pessoa ──WhatsApp──▶ Twilio ──POST /mensagem──▶ chatbot ──POST /api/v1/analyses/──▶ API do Apura
                                                  │
        até 12 s ◀── TwiML com o resultado ◀──────┤  (resposta imediata)
        mais de 12 s ◀── TwiML "estou analisando" ┤  e, quando terminar,
                     ◀── API REST da Twilio ◀─────┘  o resultado é enviado depois
```

**Por que existe a parte "depois".** A Twilio espera no máximo **15 s** pela resposta do webhook
(padrão e máximo do parâmetro `#rt`, conforme a documentação da Twilio), e a API do Apura tem até
**30 s** (RNF01). Se a análise passa de `SYNC_WAIT_SECONDS` (12 s), o webhook responde na hora
"Recebi o texto e estou analisando…" (visibilidade do estado do sistema, Nielsen) e a análise
continua numa thread. Quando termina, o resultado é enviado pela API REST da Twilio. A janela de
atendimento de 24 h do WhatsApp está aberta, porque a pessoa acabou de escrever.
Isso exige `TWILIO_ACCOUNT_SID`. Sem ele, o chatbot pede para a pessoa enviar de novo, em vez de
prometer o que não pode cumprir.

### O que o chatbot entende

| A pessoa envia | O chatbot faz |
|---|---|
| Texto de notícia | Analisa (a API aplica as regras: 50 a 5.000 caracteres, português) |
| `oi`, `ajuda`, `menu`, `como funciona`… | Explica como usar |
| Só um link | Envia como link: a **API** abre a página e extrai a notícia (scraper do back end) |
| Link sem `https://` (`g1.globo.com/…`) | Completa com `https://` e envia como link |
| Um link com comentário curto (`olha isso https://…`) | Envia como link: o comentário tem menos de 50 caracteres e não poderia ser analisado sozinho |
| Imagem, áudio, documento (mesmo com legenda) | Avisa que só analisa texto; nada é analisado |
| Vazio, emoji ou pontuação | Pede o texto |
| Texto de 50 caracteres ou mais com um link no meio | É texto: analisa o texto, não a página |

Com `URL_INPUT_ENABLED=false`, qualquer link recebe na hora "a análise por link ainda não está
disponível", sem chamar a API.

Erros de link usam os códigos reais do scraper (`paywall_or_forbidden`, `url_timeout`,
`http_error`…, em `services/errors.py`) e viram "Não conseguimos abrir essa página". Quando a
página tem texto de menos ou demais, a resposta fala da **página**, e não de "seu texto".

### Exemplo de resposta (API real, classificador simulado)

```
*Status: Alto risco*
Indícios fortes de risco. Evite repassar e procure referências verificáveis.
Índice de risco: 92,7 de 100. É um indicador de risco, não a chance de a notícia ser falsa.

*Alegação analisada* (resumo automático)
“URGENTE!!!”

*O que o Apura encontrou*
• O padrão de escrita do texto se parece com o de notícias falsas vistas no treinamento do modelo.
• Foram encontradas expressões apelativas: “compartilhe”, “urgente”.
• O texto usa pontuação excessiva, como várias exclamações.
• Esses indicadores de linguagem são apenas sinais auxiliares e não provam que a notícia é falsa.

*Limitações*
• O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.
• ...

*O que fazer agora*
• Procure a fonte original da informação antes de compartilhar.
• ...

Análise feita por computador, como apoio à leitura crítica. Não houve verificação humana. Confira a fonte original antes de compartilhar.
Data da análise: 08/10/2026 09:32
```

Regras que a resposta cumpre: o **status vem primeiro** (RF16); a **análise inconclusiva** nunca
mostra índice nem vira baixo ou alto risco, e diz que não deve ser usada para afirmar que a
notícia é verdadeira ou falsa (RF14, RF16, RF18); **nunca afirma verificação humana** (RF18);
as **fontes** aparecem com link quando a API as trouxer (RF17). Cada mensagem tem no máximo
1.600 caracteres, o limite da Twilio; respostas maiores são divididas entre seções.

## Executar

Requisitos: Python 3.12 ou mais novo (testado com 3.13). Confira com `python3 --version`. Se o
seu for mais antigo e você não puder instalar programas, o [uv](https://docs.astral.sh/uv/) baixa
um Python para a sua pasta, sem administrador: `uv venv --python 3.13 .venv`. Nesse caso instale
as dependências com `uv pip install -r requirements-dev.txt` (o ambiente do uv não traz o `pip`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python app.py
```

Preencha `TWILIO_AUTH_TOKEN` e `APURA_API_BASE_URL` no `.env`. O servidor sobe em
`http://localhost:5000`, e `GET /saude` responde ok.

No macOS 12 ou mais novo, a porta 5000 costuma estar ocupada pelo "Receptor AirPlay". Se o
`curl` na porta 5000 responder 403 ou o servidor não subir, use outra: `PORT=5001 python app.py`.

### Testar sem Twilio e sem o back end

Duas ferramentas em `tools/` deixam você conversar com o chatbot no terminal. Nenhuma precisa de
conta, de internet ou do back end.

```bash
python tools/simulate.py --fake-api
```

O simulador envia cada mensagem à **mesma rota `POST /mensagem`** do chatbot, que usa o **mesmo
código** do WhatsApp (interpretar a mensagem, chamar a API, montar a resposta, dividir em
mensagens de até 1.600 caracteres, avisar "estou analisando"). Só a Twilio é trocada: a assinatura
não é conferida, e o resultado enviado "depois do prazo" aparece no terminal.

| Comando | O que faz |
|---|---|
| `/exemplos` | Lista os 10 textos prontos |
| `/1` a `/10` | Envia um deles: alto risco, poucos sinais, requer atenção, inconclusiva, com fontes, texto curto, idioma não suportado, muitas solicitações, serviço indisponível, análise demorada |
| `/link`, `/midia` | Um link sozinho; uma imagem |
| `/arquivo CAMINHO` | Envia o conteúdo de um arquivo de texto (para testar mensagens longas) |
| `/logs` | Mostra os logs do chatbot (sem telefone nem texto) |
| `/sair` | Encerra |
| qualquer outra coisa | É enviada como mensagem |

A **API de mentirinha** (`tools/fake_apura_api.py`) responde no formato real da API v1, mas **não
analisa nada**: escolhe o resultado pelas palavras do texto, ou do endereço quando é um link (a lista está no começo do arquivo), e
cada explicação começa com um aviso de que é fixa. Os resultados com fontes usam o formato
**proposto** (a API real ainda não o tem). Para usá-la com o chatbot de verdade:

```bash
python tools/fake_apura_api.py --port 8000 &
TWILIO_VALIDATE_SIGNATURE=false APURA_API_BASE_URL=http://127.0.0.1:8000/api python app.py &

curl -s -X POST http://localhost:5000/mensagem \
  --data-urlencode "Body=URGENTE: órgão público confirma que todos receberão R\$ 5.000 amanhã. Compartilhe com todos." \
  --data-urlencode "From=whatsapp:+5561999990000" --data-urlencode "To=whatsapp:+14155238886" \
  --data-urlencode "NumMedia=0"
```

A API de mentirinha fica em `http://127.0.0.1:8000/api`. Evite `!` dentro de aspas duplas no
terminal: o zsh e o bash o tratam como histórico de comandos.

A resposta é o TwiML (XML) que a Twilio receberia. Sem `TWILIO_VALIDATE_SIGNATURE=false`, o mesmo
`curl` recebe **403**, que é o comportamento correto.

### Testar com o WhatsApp (sandbox da Twilio)

1. Suba a API do Apura (back end) e o chatbot.
2. Exponha o chatbot com um túnel HTTPS (por exemplo, ngrok) e coloque a URL completa em
   `PUBLIC_WEBHOOK_URL` (ex.: `https://abc123.ngrok.app/mensagem`). A assinatura da Twilio é
   calculada sobre essa URL; se ela não bater, o chatbot responde 403.
3. No console da Twilio, em *WhatsApp Sandbox*, informe a mesma URL em *When a message comes in*
   (método POST) e entre no sandbox pelo WhatsApp com o código que o console mostra.
4. Envie um texto de notícia.

Sem Twilio, para desenvolver: `TWILIO_VALIDATE_SIGNATURE=false` aceita chamadas sem assinatura
(o chatbot avisa no log). **Nunca use isso em produção.**

## Testes

```bash
pytest
ruff check . && ruff format --check .
```

São 323 testes, sem rede.

Os testes cobrem: divisão de mensagens; leitura de configuração; cliente da API (todos os códigos
de erro, tempo limite, versão incompatível); texto das respostas (RF14, RF16 a RF18); fluxo de
resposta imediata e de resultado enviado depois; assinatura da Twilio (válida, ausente, adulterada,
URL diferente, atrás de proxy); envio pelo SDK real da Twilio com a rede interceptada; e a garantia
de que **nenhum log contém telefone, texto da pessoa ou segredo** (RNF10).
Os 63 testes de `tests/test_tools.py` conferem as ferramentas de teste manual: cada exemplo do
simulador provoca a situação que anuncia, e o cliente real do chatbot entende a API de mentirinha.

Além disso, foi feita uma verificação com o **back end real** (Django + DRF, classificador
simulado): os quatro status, texto curto, idioma não suportado, texto longo, limite de requisições
(429 com `Retry-After`), todos lidos corretamente pelo chatbot. A entrada por link foi verificada
com o back end real e o modelo BERTimbau: notícia da Agência Brasil (link sozinho e com
comentário) e site inexistente.

## Implantação

**Docker.** `docker build -t apura-whatsapp .` e `docker run --env-file .env -p 5000:5000 apura-whatsapp`.
O contêiner roda sem privilégios e usa gunicorn com threads (cada análise espera a API numa thread).

**Junto do back end (docker-compose).** Exemplo de serviço, na mesma rede do `web`:

```yaml
  whatsapp:
    build: ./whatsapp
    restart: always
    env_file: ./whatsapp/.env
    environment:
      - APURA_API_BASE_URL=http://web:8000/api
    expose:
      - "5000"
```

Duas coisas precisam ser combinadas com quem cuida do back end:

- `web` (o nome usado em `APURA_API_BASE_URL`) deve estar em `DJANGO_ALLOWED_HOSTS`; senão o
  Django recusa a chamada com 400.
- A API limita **30 requisições por minuto por endereço** (`API_ANON_RATE`). Todo o tráfego do
  WhatsApp sai de um endereço só, então esse limite passa a valer para **todas as pessoas juntas**.
  Quando passar disso, o chatbot responde "Muitas solicitações" com o tempo de espera.

## Privacidade (RNF10)

- **Nenhum log tem telefone, texto da pessoa ou segredo.** O RosaIA registrava ambos; aqui só
  entram campos de uma lista fixa (`services/safe_log.py`): tipo da mensagem, quantidade de
  caracteres, status, tempo, código de erro e o UUID da análise. Um teste garante isso em todos
  os caminhos (sucesso, erro da API, defeito inesperado, falha de envio).
- **O telefone não vai para a API.** O chatbot não usa o cabeçalho `X-Visitor-Id` (não há
  identificador de visitante no WhatsApp). Só o texto (ou o link) é enviado.
- **O chatbot não guarda nada**: não há banco, arquivo nem cache de mensagens.
- **A Twilio e o WhatsApp também processam as mensagens.** A retenção do conteúdo na Twilio é
  configurada na conta Twilio. O grupo deve conferir essa configuração e mencioná-la na política
  de privacidade.
- Segredos só vêm do ambiente. O webhook só aceita chamadas com assinatura válida da Twilio.

## Decisões a confirmar

Estas escolhas foram feitas por falta de requisito e **precisam de confirmação do grupo**:

1. **Limite de 3 análises/24 h (RF33).** Vale para "cada navegador" na web. No WhatsApp **não há
   limite por pessoa**: só o limite de requisições da API. Definir se o canal terá um.
2. **Texto de até 1.600 caracteres.** A documentação da Twilio informa que o `Body` recebido tem
   "até 1600 caracteres", abaixo dos 5.000 que a API aceita. Textos maiores podem chegar cortados;
   quando a mensagem chega com exatamente 1.600, a resposta acrescenta esse aviso às limitações.
   Confirmar o comportamento real em teste com o sandbox.
3. **Imagens e áudios** não são analisados (o requisito só prevê texto e link). A resposta diz isso.
4. **Link.** A API já abre links, então o padrão é `URL_INPUT_ENABLED=true`. Um link com
   comentário de menos de 50 caracteres vai como link; com comentário maior, vai como texto (o
   texto que a pessoa recebeu é a alegação). Uma manchete compartilhada com mais de 50 caracteres
   é analisada como texto, só a manchete: confirmar se o grupo prefere analisar a página.
5. **Fontes e falha na consulta de evidências** (Etapa 3): o formato assumido (`relation`,
   `publisher`, `title`, `url`; `evidence.failed` ou `evidence.error`) e os códigos `invalid_url`,
   `page_unreachable`, `evidence_unavailable` são **propostas**, iguais às da interface web. Estão
   marcados `PROPOSTA` no código. Trocar quando o back end definir.
6. **Comandos** (`oi`, `ajuda`, `menu`…), a mensagem "estou analisando" e o link "Detalhes
   completos" (`WEB_BASE_URL`, opcional) não vêm de requisito.
7. **Resumo da alegação.** A API devolve `confirmed_by_user: false`; a resposta chama de "resumo
   automático". Quando o RF06 existir (confirmar ou corrigir a alegação), o WhatsApp precisará de
   um jeito de fazer isso.
8. **Nome.** O texto da API para idioma não suportado ainda diz "Fake Eyes". O chatbot usa texto
   próprio, com o nome Apura.

## Limitações conhecidas

- A resposta depois do prazo depende de o processo continuar vivo: se o chatbot reiniciar no meio
  de uma análise, aquela resposta se perde (a pessoa pode enviar de novo). Não há fila nem banco.
- As mensagens enviadas depois pela API REST podem, em tese, chegar fora de ordem; há uma pausa
  de 0,6 s entre elas para reduzir isso. Na resposta imediata, a ordem é a do TwiML.
- Não testado com a Twilio real (sem credenciais neste ambiente) nem com o build do Docker.
