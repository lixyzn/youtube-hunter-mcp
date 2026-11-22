# 📘 DOCUMENTAÇÃO — YouTube Hunter MCP (estado atual: 26/10/2026)

## CHANGELOG — 26/10/2026

### 🔴→🟢 Camada L1B (Innertube `get_panel`) — transcrição restabelecida

**Problema medido:** o IP da máquina foi bloqueado por reputação no endpoint de
legendas `/api/timedtext` (HTTP 429 “Sorry...”). Isso mata **todas** as rotas
conhecidas — inclusive a interface real do YouTube no navegador e o yt-dlp com
PO Token válido (`pot=...&potc=1&c=WEB` já injetado na URL, ainda 429).

**Solução:** nova camada **L1B** (`src/youtube_hunter_mcp/innertube_transcript.py`)
que pede a transcrição à API JSON do YouTube (`POST /youtubei/v1/get_panel`,
`panelId=PAmodern_transcript_view`) em vez do endpoint de legendas. O `params`
é um blob protobuf determinístico com o video id, montado localmente — sem
navegador, sem PO Token, sem cookies.

**Resultado real:** 3 de 4 casos do teste de aceitação resolvidos pela L1B
(incluindo o vídeo NANA, que falhava em todas as camadas), ~1,5–3 s por vídeo,
transcrição inteira em uma requisição (129 segmentos em vídeo de 19 min). O caso
sem legenda falha de forma limpa em 2,7 s.

**Arquivos:** `innertube_transcript.py` (novo), `transcript_sources.py` (L1B,
L1 deixa de ser terminal em “subtitles disabled”, cache 2 → 3),
`docs/TRANSCRIT.md`, `scripts/test_transcript_matrix.py`,
`scripts/verify_mcp_handshake.py`, `scripts/verify_tool_transcript.py`.
Contrato público inalterado: as 10 tools mantêm assinatura e formato.

### Motor multi-estado (L0–L5)

- Nova transcrição multi-estado `L0–L5`: cache local, `youtube-transcript-api`,
  yt-dlp com rotação de clients, Playwright DOM, Playwright/rede e API externa
  opcional.
- Adicionados `source_chain`, `cached` e `warnings` sem remover o contrato
  público; as assinaturas das 10 tools MCP permanecem iguais.
- Adicionados cache, rate limit, circuit breaker de IP bloqueado, limite de
  sessões de browser, cookies, proxy e clientes yt-dlp configuráveis.
- Corrigido o parse de views: idades como `8mo ago` não são mais tratadas
  como contagem de views.
- Detalhes e saída real: `docs/TRANSCRIT.md`.

> Documento de referência do servidor. Escrito **antes** da reescrita da camada de transcrição, para servir de baseline e de contrato de compatibilidade.
> Repositório: `D:\mcp\youtube-hunter-mcp` · Entry point MCP: `src/youtube_hunter_mcp/server.py` · Console script: `youtube-hunter-mcp`

---

## 1. O QUE É

Servidor MCP (FastMCP, stdio) que dá a um agente: **olhos no YouTube** (Playwright), **mineração de canal**, **transcrição**, **OCR de capa** e **engenharia narrativa de roteiros** (WPM, loops de curiosidade, dossiês Markdown).

Conceito central: o canal **BUNKAI** (análise psicológica de personagens de anime) usa isto como **fábrica de pesquisa de mercado** — relatórios de nicho, estrutura narrativa, padrões de capa e títulos.

---

## 2. ARQUITETURA (módulos)

| Módulo | Responsabilidade | Dependências |
| :-- | :-- | :-- |
| `server.py` | Registro das 10 tools MCP (FastMCP) + ponto de entrada `main()` | `mcp` |
| `browser.py` | Motor Playwright headless: raspa canais, busca, páginas de vídeo, screenshots, captura de legendas via rede | `playwright` |
| `transcript.py` | Fachada pública compatível para transcrição | `transcript_sources` |
| `transcript_sources.py` | Motor multi-estado L0–L5 (L0 cache, L1 API, **L1B Innertube**, L2 yt-dlp, L3 DOM, L4 rede, L5 externo), rate limit, circuit breaker, cookies/proxy e proveniência | `youtube-transcript-api`, `yt-dlp`, `playwright`, `httpx` |
| `innertube_transcript.py` | Transcrição via `youtubei/v1/get_panel` (rota que sobrevive ao bloqueio 429 do endpoint de legendas) | `httpx` |
| `thumbnails.py` | Baixa a capa em `maxresdefault` (fallback `hq720`/`hqdefault`) e resolve dimensões | `httpx`, `pillow` |
| `thumbnail_ocr.py` | OCR das capas via RapidOCR (ONNX) + features tipográficas | `rapidocr-onnxruntime` |
| `channel_miner.py` | Coleta de vídeo + baseline do canal + outliers | `browser`, `thumbnails` |
| `niche_outliers.py` | Busca outliers virais (views vs inscritos) | `browser`, `transcript`, `thumbnail_ocr` |
| `dossier_generator.py` | Gera dossiê Markdown por canal e por nichos de outliers | — |
| `pacing_analyzer.py` | WPM, classificação de ritmo, loops de curiosidade, fórmula narrativa | `transcript` |
| `packaging_analyzer.py` | Sinergia Título + Capa, detecção de redundância, risco mobile e triggers psicológicos | `thumbnail_ocr` |
| `thumbnail_grid.py` | Montagem de grades comparativas (moodboards) com badges para visão multimodal | `pillow` |
| `mining_report.py` | Persistência de mineração, catálogo de inteligência e dashboard HTML interativo | — |
| `utils.py` | Extração de ID, normalização de canal, parse de views, sanitização | — |

**Fluxo típico:** `yt_search` → `yt_find_viral_outliers` → `yt_deep_mine_channel` (gera dossiê) → `yt_build_thumbnail_grid` (visão para IA) → `yt_dissect_packaging` (análise de CTR) → `yt_get_mining_catalog` (visão geral).

---

## 3. AS 14 TOOLS

| Tool | Assinatura principal | Output |
| :-- | :-- | :-- |
| `yt_deep_mine_channel` | `channel_url_or_handle`, `mode` (popular/latest), `max_videos`, `download_thumbnails`, `fetch_transcripts`, `generate_dossier`, `lang_preference` | baseline do canal + tabela de outliers + thumbnails + hooks + dossiê |
| `yt_find_viral_outliers` | `query`, `max_search_results`, `min_multiplier`, `max_channel_subscribers`, `enrich_top_n` | vídeos com views/inscritos + capa + OCR + hook + dossiê de nicho |
| `yt_build_thumbnail_grid` | `video_urls_or_ids`, `subfolder_or_query`, `grid_title`, `max_items`, `columns` | Moodboard comparativo de capas com badges (#1, views, multiplicador) para visão de IA |
| `yt_get_mining_catalog` | *(sem argumentos)* | Catálogo executivo com métricas globais, canais, nichos e sumário Markdown |
| `yt_dissect_packaging` | `title`, `thumbnail_path_or_url`, `thumbnail_text` | Sinergia Título-Capa, cálculo de redundância de palavras, gatilhos de CTR e recomendações |
| `yt_generate_mining_report` | `output_name` | Painel web HTML interativo com filtros e ordenação no navegador |
| `yt_search` | `query`, `max_results`, `capture_screenshot` | cards de busca (título, canal, views, idade, thumb) |
| `yt_get_transcript` | `url_or_id`, `lang_preference`, `include_timestamps`, `force_browser` | hook 60s + roteiro completo + snippets |
| `yt_parse_custom_transcript` | `transcript_text`, `video_id`, `hook_duration_seconds`, `words_per_minute` | limpeza + hook + WPM estimado (offline) |
| `yt_analyze_pacing` | `video_url_or_id`, `lang_preference`, `pasted_transcript` | WPM, ritmo do gancho, loops/min, recomendações |
| `yt_inspect_video` | `url_or_id`, `download_thumbnail_file`, `max_comments` | descrição, canal, top comentários, capa |
| `yt_download_thumbnails` | `video_urls_or_ids`, `folder_name` | paths + dimensões + file URIs |
| `yt_extract_thumbnail_text` | `image_path_or_video_url` | linhas OCR + confiança + tipografia |
| `yt_capture_screenshot` | `url`, `output_name` | path do PNG 1080p |

---

## 4. INSTALAÇÃO E OPERAÇÃO

```powershell
# venv local (já existe e é o que o MCP usa)
D:\mcp\youtube-hunter-mcp\.venv\Scripts\python.exe

# rodar manualmente (stdio)
cd D:\mcp\youtube-hunter-mcp
.\.venv\Scripts\youtube-hunter-mcp.exe          # entry point oficial (preferido)
.\.venv\Scripts\python.exe -m youtube_hunter_mcp.server   # equivalente (gera RuntimeWarning)

# testar o servidor
D:\mcp\youtube-hunter-mcp\.venv\Scripts\python.exe -c "import youtube_hunter_mcp, mcp; print('ok')"
```

**Registro no OpenCode** (`C:\Users\fernando\.config\opencode\opencode.json`):
```json
"youtube-hunter": {
  "type": "local",
  "command": ["cmd.exe", "/d", "/c", "cd", "/d", "D:\\mcp\\youtube-hunter-mcp", "&&",
              "D:\\mcp\\youtube-hunter-mcp\\.venv\\Scripts\\youtube-hunter-mcp.exe"],
  "enabled": true
}
```
> O `cd /d` fixa o cwd no projeto: `BASE_DOWNLOAD_DIR` e `DOSSIERS_DIR` resolvem para `D:\mcp\youtube-hunter-mcp\downloads` e `...\dossiers` (o fallback `Path(__file__).parents[2]`).

**Dependências instaladas** (venv, Python 3.11): `mcp 1.30`, `playwright 1.63`, `rapidocr-onnxruntime 1.4.4`, `youtube-transcript-api 1.2.4`, `yt-dlp 2026.8.19`, `pillow 12.3`, `httpx 0.28.1`, `beautifulsoup4 4.15`.
**Navegador**: Chromium do Playwright instalado em `%LOCALAPPDATA%\ms-playwright` (`chromium-1248`, `chromium_headless_shell-1248`, `ffmpeg-1013`).

---

## 5. VARIÁVEIS DE AMBIENTE (atuais)

| Variável | Efeito | Default |
| :-- | :-- | :-- |
| `YT_HUNTER_DOWNLOADS` | Sobrescreve a pasta de downloads/thumbnails/screenshots | `D:\mcp\youtube-hunter-mcp\downloads` |
| `YT_HUNTER_TRANSCRIPT_CACHE` | Cache JSON de transcrições | `D:\mcp\youtube-hunter-mcp\downloads\transcripts_cache` |
| `YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE` | Ignora cache existente quando `1` | desligado |
| `YT_HUNTER_COOKIES` | Caminho de cookies.txt Netscape | vazio |
| `YT_HUNTER_PROXY` | Proxy HTTP para API e yt-dlp | vazio |
| `YT_HUNTER_TRANSCRIPT_CLIENTS` | Rotação de clients do yt-dlp | `android_vr,tv,web_embedded,android,ios,mweb,web` |
| `YT_HUNTER_MAX_CONCURRENT_BROWSERS` | Sessões Playwright simultâneas | `2` |
| `YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS` | Intervalo mínimo entre chamadas de rede | `1500` |
| `YT_HUNTER_TRANSCRIPT_BLOCK_COOLDOWN_SEC` | Cooldown do circuit breaker de IP | `900` |
| `YT_HUNTER_TRANSCRIPT_API_URL` | Endpoint externo opcional | vazio |
| `PLAYWRIGHT_BROWSERS_PATH` | Caminho dos navegadores | `%LOCALAPPDATA%\ms-playwright` |

---

## 6. SAÍDAS EM DISCO

| Caminho | Conteúdo |
| :-- | :-- |
| `D:\mcp\youtube-hunter-mcp\downloads\thumbnails\<canal ou pasta>\` | capas em `maxresdefault` |
| `D:\mcp\youtube-hunter-mcp\downloads\screenshots\` | PNGs 1080p |
| `D:\mcp\youtube-hunter-mcp\dossiers\DOSSIER_<Canal>_<timestamp>.md` | dossiês por canal |
| `D:\pesquisa de mercado anime\` | **cópia de trabalho** da pesquisa (relatórios, 24 dossiês, 460 capas, raw) |
| `D:\cerebro\` | vault Obsidian do canal BUNKAI (24 notas, 114 wikilinks) |

---

## 7. PROBLEMAS CONHECIDOS (baseline honesto)

### 7.1 🟢 BLOQUEIO DE IP NA TRANSCRIÇÃO (contornado pela camada L1B)
**Estado:** o bloqueio de reputação no endpoint `/api/timedtext` (HTTP 429 “Sorry...”) foi **medido e confirmado** em 26/10/2026: ele atinge a `youtube-transcript-api`, o yt-dlp (com ou sem PO Token), a interface real do YouTube no navegador e todas as instâncias públicas Invidious/Piped testadas. A causa é reputação de IP, **não** falta de PO Token.
**Resolução:** a camada L1B (`innertube_transcript.py`) usa a API JSON do YouTube (`youtubei/v1/get_panel`) e entrega a transcrição completa em uma requisição HTTP, sem navegador e sem token.
**Limites que sobraram:** a rota entrega a faixa padrão do player (não há escolha livre de idioma) e quebra se o YouTube mudar o formato do painel; nesse caso as demais camadas (yt-dlp com PO Token, DOM, cookies/proxy) assumem. Cookies/proxy continuam úteis para **mídia** e para cenários de IP persistente.
**Mitigações complementares:** cache/rate limit/circuit breaker, rotação de player clients, PO Token provider local (`bgutil-ytdlp-pot-provider`, instalado e rodando em `http://127.0.0.1:4416`), captura pelo DOM, cookies Netscape (`YT_HUNTER_COOKIES`) e proxy residencial (`YT_HUNTER_PROXY`).

### 7.2 🟢 BUG DE PARSE DE VIEWS (corrigido em 26/10/2026)
`views_raw` não recebe mais strings de idade como `8mo ago`; o scraper valida
explicitamente o formato e mantém o formato de saída atual para não quebrar
consumidores.

### 7.3 🟡 FRAGILIDADE DO FALLBACK DE NAVEGADOR
`scrape_video_transcript_browser` depende de: consentimento aceito + clique no botão CC/tecla `c` + captura de resposta `timedtext` + fallback no `ytInitialPlayerResponse`. Falhou em 6 de 6 vídeos testados no fim da coleta de 26/10.

### 7.4 🟢 RUNTIME WARNING NO `-m`
`python -m youtube_hunter_mcp.server` emite `RuntimeWarning` porque `__init__.py` já importa `server`. Resolvido usando o console script `youtube-hunter-mcp.exe`.

### 7.5 🟢 DEPENDÊNCIA OCIOSA
`yt-dlp` está instalado mas não é importado em nenhum módulo de `src/` (só em scripts soltos da raiz).

### 7.6 🟡 CONTEXTO DE NAVEGADOR FIXO
`browser.py` usa sempre `locale="en-US"` e UA de Linux, para métricas consistentes. Isso **não** muda a extração de legenda, mas vale saber.

---

## 8. DECISÕES DE PRODUTO (canal BUNKAI)

- **Eixo analítico fixo:** psicologia de personagens.
- **Formato:** 1 personagem · 1 tese · 16–22 min · 168–180 WPM · 2,0–2,5 loops de curiosidade/min.
- **Embalagem:** título em inglês, narração em PT-BR, capa com 2–4 palavras emocionais + 1 rosto.
- **Fontes de verdade (medido em 26/10/2026):** `coolnugget` (personagem = 125x) · `Zoott` (tese emocional = 156x) · `RizukU` (tese PT-BR = 13,9x) · `Ishaan Kaushal` (meta-educativo = 824x). **Evitar:** recap puro (Rebobina 1,7K), rankings (0,07x), "40 detalhes" (0,43x).

---

## 9. PRÓXIMA ETAPA (o que este baseline habilita)

**Reescrever a camada de transcrição** para ser multi-estrado, com cache, rotação de clients, PO Token via navegador e captura por DOM — de modo que a coleta de centenas de transcrições volte a funcionar. Contrato de compatibilidade: **as assinaturas públicas das 10 tools não mudam**; só a robustez e a Proveniência (`extractor`) da transcrição mudam.

Detalhe completo em `docs/TRANSCRIT.md` (criado na implementação) e no changelog no topo deste arquivo.
