# Transcrição multi-estado do YouTube Hunter

## Objetivo

A extração de legendas deixou de depender exclusivamente da API HTTP. O motor
em `src/youtube_hunter_mcp/transcript_sources.py` tenta camadas independentes e
registra a proveniência em `source_chain`.

**Estado em 26/10/2026:** o IP desta máquina está com bloqueio de reputação no
endpoint `/api/timedtext` (HTTP 429 “Sorry...”), o que mata a `youtube-transcript-api`,
o `yt-dlp --write-subs` e **a própria interface do YouTube** (inclusive com PO
Token válido). A camada **L1B (Innertube `get_panel`)** foi implementada para
contornar isso e hoje é a rota que resolve a coleta em massa.

## Camadas (ordem)

- **L0 — cache local:** `downloads/transcripts_cache/<video_id>.json`. O cache
  guarda o resultado completo, `cache_version=3` e timestamp. Para invalidar,
  defina `YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE=1` antes de iniciar o servidor.
- **L1 — `youtube-transcript-api`:** rápido, mas usa HTTP puro. `IpBlocked` e
  `RequestBlocked` acionam imediatamente o circuit breaker; não há insistência
  em requisições bloqueadas. “Subtitles are disabled” **não** é mais terminal:
  a L1B ainda pode encontrar legendas automáticas.
- **L1B — Innertube `get_panel` (rota principal hoje):** pede a transcrição à
  API JSON do YouTube em vez do endpoint de legendas. Ver
  [Rota Innertube](#rota-innertube-l1b) abaixo. HTTP puro, sem navegador, sem
  PO Token, ~1,5–3 s por vídeo e a transcrição inteira em uma única resposta.
- **L2 — `yt-dlp`:** executa o binário do venv com legendas manuais e
  automáticas, `--js-runtimes node`, timeout/retries e rotação de
  `--extractor-args youtube:player_client=...`. Também aceita cookies e proxy.
  Os formatos VTT, SRT e JSON3 são convertidos para texto e timestamps.
- **L3 — Playwright DOM:** abre a página, aceita consentimento, procura
  “Show transcript”, “Mostrar transcrição” e variantes, e lê
  `ytd-transcript-segment-renderer`. Esta é a rota preferida do navegador.
- **L4 — Playwright/rede:** captura `timedtext`, aciona CC/tecla `c` e usa
  `ytInitialPlayerResponse.captions...captionTracks[].baseUrl` no contexto da
  página como fallback.
- **L5 — API externa opcional:** POST JSON `{video_id, lang}` para
  `YT_HUNTER_TRANSCRIPT_API_URL` quando configurado.

`force_browser=True` usa L3 e L4 primeiro (e cai para L1B). A API pública e as
assinaturas das 10 tools MCP não mudaram; os resultados mantêm as chaves
existentes e adicionam `source_chain`, `cached` e `warnings`.

## Rota Innertube (L1B)

Implementação: `src/youtube_hunter_mcp/innertube_transcript.py`.

O YouTube serve o painel de transcrição pelo endpoint Innertube
`POST /youtubei/v1/get_panel`, que **não** é bloqueado por reputação de IP
(ao contrário de `/api/timedtext`). A requisição precisa de:

| Campo | Valor |
| :-- | :-- |
| `context.client` | cliente `WEB`, `clientVersion` e `visitorData` extraídos da página `/watch` |
| `panelId` | `PAmodern_transcript_view` |
| `params` | blob protobuf determinístico com o video id |

O `params` é montado localmente (sem depender da UI):

```text
aa 09 0f | 0a <len(video_id)> <video_id> | 18 07
```

A resposta traz um `transcriptSegmentViewModel` por linha de legenda
(`timestamp` + `simpleText`), cobrindo o vídeo inteiro em uma requisição — sem
paginação. Testado em vídeo de 19 min: 129 segmentos, 1105 s de cobertura.

Características e limitações honestas:

- **Idioma:** o painel serve a faixa **padrão do player** e não informa qual é.
  O código detecta o idioma por stopwords (`detect_language`, en/pt/es/fr/de/it
  + detecção de script para ja/ru/ko) e cruza com as faixas anunciadas pela
  página. Se a detecção falhar, o idioma sai `und` (sem chute).
- **Manual vs automático:** inferido por heurística (se existe faixa manual
  para o idioma detectado, `is_generated=false`).
- **Escolha de idioma (`lang_preference`):** esta rota entrega a faixa padrão
  do player; se o idioma pedido não bater, a tool preenche `warnings`.
- **Sem legendas:** se o YouTube não anuncia nenhuma faixa, a falha é
  terminal e limpa em ~2 s (sem gastar navegador/yt-dlp).
- **Sem navegador, sem PO Token, sem cookies** — funciona com IP bloqueado.

## Variáveis de ambiente

| Variável | Default | Uso |
| :-- | :-- | :-- |
| `YT_HUNTER_TRANSCRIPT_CACHE` | `D:\mcp\youtube-hunter-mcp\downloads\transcripts_cache` | cache JSON |
| `YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE` | desligado | `1` ignora o cache existente |
| `YT_HUNTER_COOKIES` | vazio | cookies.txt Netscape para yt-dlp |
| `YT_HUNTER_PROXY` | vazio | proxy HTTP, por exemplo `http://user:pass@host:port` |
| `YT_HUNTER_TRANSCRIPT_CLIENTS` | `android_vr,tv,web_embedded,android,ios,mweb,web` | ordem de clients do yt-dlp |
| `YT_HUNTER_MAX_CONCURRENT_BROWSERS` | `2` | sessões Playwright simultâneas |
| `YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS` | `1500` | intervalo mínimo entre chamadas de rede |
| `YT_HUNTER_TRANSCRIPT_BLOCK_COOLDOWN_SEC` | `900` | cooldown do circuit breaker de IP bloqueado |
| `YT_HUNTER_TRANSCRIPT_API_URL` | vazio | endpoint externo opcional |

## Cookies e proxy

1. Instale a extensão Chrome **Get cookies.txt LOCALLY**.
2. Faça login no YouTube e exporte cookies em formato **Netscape** para um
   arquivo local, por exemplo `D:\mcp\youtube-hunter-mcp\cookies.txt`.
3. Configure `YT_HUNTER_COOKIES=D:\mcp\youtube-hunter-mcp\cookies.txt`.
   O arquivo é um segredo: não o versione nem o compartilhe.

Para proxy, configure `YT_HUNTER_PROXY`. A API HTTP e o yt-dlp recebem a
mesma configuração. Cookies e proxy juntos costumam ser a combinação mais
efetiva em IPs residenciais.

## PO Token (opcional, e não resolve o 429 deste IP)

O YouTube exige PO Token (BotGuard) para requisições de legendas no cliente
`web`. Foi testado de verdade aqui, com o provider oficial:

```powershell
# provider instalado no venv
D:\mcp\youtube-hunter-mcp\.venv\Scripts\python.exe -m pip install bgutil-ytdlp-pot-provider

# servidor local (o repo fica em .tools\bgutil-pot\repo)
cd D:\mcp\youtube-hunter-mcp\.tools\bgutil-pot\repo\server
npx tsc --outDir dist
node dist/main.js --port 4416
# PING -> {"server_uptime":...,"version":"2.0.2"}
```

E o uso pelo yt-dlp:

```powershell
yt-dlp.exe --skip-download --write-auto-subs --sub-langs "en.*" `
  --extractor-args "youtube:player_client=web;po_token=web.gvs+web.player+web.subs" `
  --extractor-args "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416" <url>
```

Para subir o provider em um comando (compila se preciso e testa o `/ping`):

```powershell
D:\mcp\youtube-hunter-mcp\scripts\start_pot_provider.cmd
```

**Resultado real medido em 26/10/2026:** o token `subs` **é** gerado e injetado
(`pot=...&potc=1&c=WEB` aparece na URL final), mas o `/api/timedtext` continua
devolvendo **HTTP 429**. O mesmo 429 acontece com a UI real do YouTube no
navegador, com `android_vr`, `web_safari`, `mweb`, `tv`, com e sem token, e com
`fmt=json3|srv3|vtt|ttml`. Conclusão: o bloqueio é de **reputação de IP no
endpoint de legendas**, não de token. Por isso a camada L1B existe.

O PO Token continua útil para **baixar mídia** (formatos de vídeo) e para
cenários em que o IP não está penalizado. Ele é opcional: se o servidor não
estiver no ar, todas as demais camadas continuam funcionando.

## Troubleshooting

- **429, “Too Many Requests” ou poeira no console:** o IP foi bloqueado no
  endpoint de legendas. A camada L1B (Innertube) contorna esse bloqueio; se
  ela falhar, use cache, reduza `YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS` somente
  se ainda houver capacidade e configure proxy/cookies.
- **“Sign in to confirm you’re not a bot”:** normalmente falta cookie de
  navegador ou PO Token. Exporte cookies Netscape; como último recurso use
  `yt-dlp-getpot-wpc`.
- **L1B `panel returned no transcript segments`:** o vídeo não tem faixas de
  legenda (o YouTube não anuncia nenhuma) — falha terminal e limpa.
- **L1B `get_panel HTTP 4xx/5xx`:** o YouTube mudou o formato da requisição.
  Verifique `INNERTUBE_CLIENT_VERSION` e o `panelId` em
  `innertube_transcript.py`; a página `/watch` entregue pelo próprio YouTube é
  a referência do formato.
- **L3 sem segmentos:** o YouTube pode mudar o DOM. Verifique o texto do
  botão no idioma da página e tente novamente; L4 continua sendo executada.
- **L2 `Requested format is not available`:** esse client não oferece a faixa
  de legenda; a rotação tenta o próximo client.
- **Falha limpa:** vídeos indisponíveis ou sem legendas retornam
  `success=false`, `error` e a cadeia de tentativas, sem exceções.

## Limitações honestas

A rota L1B resolve o bloqueio de IP do endpoint de legendas, mas não é uma
garantia absoluta de “quantas transcrições se quiser”: o YouTube pode mudar o
formato do painel (aí a L1B quebra e as demais camadas assumem), vídeos sem
legendas continuam indistinguíveis de falhas temporárias em alguns clients, e a
rota entrega a **faixa padrão do player** — não é possível escolher livremente
o idioma (o pedido de idioma entra como `warnings` quando não bate). O idioma
detectado por stopwords é heurístico (`und` quando sem sinal). Cache, rate
limit, rotação de clients e proveniência reduzem o impacto, mas não eliminam
os bloqueios. O modo headless também depende do Chromium instalado pelo
Playwright.

## Teste de aceitação (saída real de 26/10/2026)

Executado com:

```powershell
$env:YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE="1"
D:\mcp\youtube-hunter-mcp\.venv\Scripts\python.exe scripts\test_transcript_matrix.py
```

```text
TRANSCRIPT ACCEPTANCE MATRIX
================================================================================

[without captions (expected clean failure)] aqz-KE-bpKQ
  success=False resolver=NONE time=2.72s words=0 language=en
  error=No transcript found by any configured source.
  chain=[{"layer": "L1", "status": "failed", "reason": "transcripts disabled: ..."},
         {"layer": "L1B", "status": "failed", "reason": "panel returned no transcript segments"},
         {"layer": "L1B", "status": "failed", "reason": "YouTube advertises no caption track for this video"}]

[manual EN] dQw4w9WgXcQ
  success=True resolver=L1B time=3.44s words=487 language=en
  chain=[{"layer": "L1", "status": "failed", "reason": "IP blocked: ..."},
         {"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"}]

[auto PT-BR] 9bZkp7q19f0
  success=True resolver=L1B time=1.38s words=194 language=ko
  chain=[{"layer": "L1", "status": "failed", "reason": "circuit breaker open (IP blocked)"},
         {"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"}]

[previously failed NANA] Oh5gXGGlwis
  success=True resolver=L1B time=1.50s words=3106 language=pt
  chain=[{"layer": "L1", "status": "failed", "reason": "circuit breaker open (IP blocked)"},
         {"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"}]

================================================================================
completed: 4 cases, 1 clean failures
```

Leitura do resultado:

- **3 de 4 casos resolvidos pela L1B**, incluindo o vídeo NANA (`Oh5gXGGlwis`),
  que falhava em todas as camadas antes desta implementação.
- O caso sem legenda falha de forma **limpa e rápida** (2,7 s): o YouTube não
  anuncia nenhuma faixa, o que é tratado como terminal.
- `9bZkp7q19f0` aparece como “PT-BR” no script de teste, mas o vídeo é coreano:
  a detecção por stopwords/script retorna `ko`, que é o idioma real da faixa
  padrão do player.
- Nenhuma camada precisou de navegador, cookies, proxy ou PO Token.

### Verificação ponta a ponta pelo protocolo MCP

`scripts/verify_tool_transcript.py` chama a tool `yt_get_transcript` num
servidor MCP real (stdio):

```text
=== Oh5gXGGlwis (pt) ===
success: True | extractor: innertube_panel | words: 3106 | lang: pt | cached: False
   chain: L1 failed IP blocked
   chain: L1B success innertube get_panel transcript
   hook: Escolha o tema do vídeo. Animação, [música] terror, filmes, variedades. ...

=== dQw4w9WgXcQ (en) ===
success: True | extractor: innertube_panel | words: 487 | lang: en | cached: False
   chain: L1 failed circuit breaker open (IP blocked)
   chain: L1B success innertube get_panel transcript
   hook: [♪♪♪] ♪ We're no strangers to love ♪ ♪ You know the rules and so do I ...
```

`scripts/verify_mcp_handshake.py` confirma que o servidor sobe e continua
expondo exatamente as 10 tools públicas (`yt_analyze_pacing`,
`yt_capture_screenshot`, `yt_deep_mine_channel`, `yt_download_thumbnails`,
`yt_extract_thumbnail_text`, `yt_find_viral_outliers`, `yt_get_transcript`,
`yt_inspect_video`, `yt_parse_custom_transcript`, `yt_search`).
