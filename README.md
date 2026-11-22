# 🦅 YouTube Hunter MCP

Servidor **MCP (Model Context Protocol)** local que dá a agentes de IA capacidade de **pesquisar, minerar e analisar o YouTube**: canais, outliers virais, transcrições, thumbnails com OCR, ritmo de roteiro, dossiês em Markdown e dashboards HTML.

Sem Google Cloud API, sem cotas e sem login obrigatório.

> ⚠️ **Uso responsável:** este projeto é voltado a pesquisa e análise. Respeite os [Termos de Serviço do YouTube](https://www.youtube.com/t/terms), direitos autorais e limites de requisição. Use cookies/proxy apenas em contas e conteúdos que você tem direito de acessar.

---

## 📋 Índice

- [Recursos principais](#-recursos-principais)
- [As 14 ferramentas](#-as-14-ferramentas-tools)
- [Como a transcrição funciona](#-como-a-transcrição-funciona)
- [Requisitos](#-requisitos)
- [Instalação](#-instalação)
- [Configuração no cliente MCP](#-configuração-no-cliente-mcp)
- [Variáveis de ambiente](#-variáveis-de-ambiente)
- [Dados gerados](#-dados-gerados)
- [Estrutura do projeto](#-estrutura-do-projeto)
- [Verificação e testes](#-verificação-e-testes)
- [Limitações conhecidas](#-limitações-conhecidas)

---

## ✨ Recursos principais

- **Mineração de canais** — vídeos mais populares ou recentes, média de views, outliers e download das capas em resolução máxima.
- **Outliers de nicho** — cruza views do vídeo com inscritos do canal para achar conteúdo que viralizou sem autoridade de marca.
- **Transcrições em camadas** — cache local, `youtube-transcript-api`, Innertube, `yt-dlp`, Playwright (DOM/rede) e API externa opcional, com proveniência (`source_chain`).
- **OCR de thumbnails** — lê o texto da capa com RapidOCR/ONNX e identifica tipografia, números e gatilhos de clique.
- **Análise de ritmo** — WPM, densidade de perguntas e loops de curiosidade para avaliar retenção.
- **Auditoria de packaging** — detecta redundância entre título e capa, risco de corte no mobile e palavras de poder.
- **Dossiês e dashboard** — gera Markdown compatível com Obsidian e um painel HTML responsivo com filtros e ordenação.
- **Visão multimodal** — screenshots 1080p e grades comparativas de capas para modelos com visão.

---

## 🛠️ As 14 ferramentas (*tools*)

| # | Tool | O que faz |
|---|------|-----------|
| 1 | `yt_deep_mine_channel` | Minera um canal de ponta a ponta: vídeos, outliers, thumbnails, roteiros/ganchos e dossiê. |
| 2 | `yt_find_viral_outliers` | Busca um nicho e filtra vídeos com views muito acima do tamanho do canal. |
| 3 | `yt_extract_thumbnail_text` | OCR de uma thumbnail (arquivo local, URL ou ID do vídeo). |
| 4 | `yt_analyze_pacing` | Analisa WPM, perguntas por minuto e loops de curiosidade de um vídeo ou texto colado. |
| 5 | `yt_search` | Pesquisa no YouTube e retorna cards ranqueados; opcionalmente captura screenshot. |
| 6 | `yt_get_transcript` | Extrai transcrição e gancho inicial em qualquer idioma, com timestamps opcionais. |
| 7 | `yt_parse_custom_transcript` | Limpa e analisa um roteiro colado manualmente, sem fazer requisições. |
| 8 | `yt_inspect_video` | Raio-X de um vídeo: metadados, descrição, tags, capa e comentários populares. |
| 9 | `yt_download_thumbnails` | Baixa capas em lote na melhor resolução disponível. |
| 10 | `yt_capture_screenshot` | Captura screenshot 1080p de qualquer página do YouTube. |
| 11 | `yt_generate_mining_report` | Gera o dashboard HTML com todos os canais e nichos minerados. |
| 12 | `yt_build_thumbnail_grid` | Monta uma grade/moodboard de capas com badges de ranking e métricas. |
| 13 | `yt_get_mining_catalog` | Catálogo executivo de tudo que já foi minerado, com resumo em Markdown. |
| 14 | `yt_dissect_packaging` | Audita a sinergia entre título e capa e entrega veredito de CTR. |

---

## 🔍 Como a transcrição funciona

O motor tenta camadas independentes e registra cada tentativa em `source_chain`:

```
L0  cache local (JSON)
L1  youtube-transcript-api
L1B Innertube get_panel (POST /youtubei/v1/get_panel)
L2  yt-dlp com rotação de player clients
L3  Playwright lendo o painel de transcrição no DOM
L4  Playwright interceptando timedtext / ytInitialPlayerResponse
L5  API externa opcional
```

A camada **L1B** foi adicionada porque o endpoint `/api/timedtext` pode retornar HTTP 429 por reputação de IP, o que também derruba `yt-dlp` e a interface web. O Innertube devolve a transcrição em uma única requisição HTTP, sem navegador e sem PO Token.

O motor inclui rate limit com jitter, semáforo para navegadores, cache e circuit breaker após bloqueio. Detalhes, configuração de cookies/proxy e limitações honestas estão em [`docs/TRANSCRIT.md`](docs/TRANSCRIT.md).

---

## ✅ Requisitos

- **Python 3.10+** (o projeto fixa 3.11 em `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** para instalar e executar
- **Playwright + Chromium** para scraping e screenshots
- ~1 GB de espaço livre para dependências, modelos de OCR e dados baixados

---

## 🚀 Instalação

```powershell
git clone https://github.com/lixyzn/youtube-hunter-mcp.git
cd youtube-hunter-mcp

uv sync
uv run playwright install chromium
```

No Linux, se faltarem bibliotecas de sistema para o Chromium:

```bash
uv run playwright install --with-deps chromium
```

Teste rápido do servidor (stdio, aguardando um cliente MCP):

```powershell
uv run youtube-hunter-mcp
```

Ou, de forma equivalente:

```powershell
uv run python -m youtube_hunter_mcp.server
```

---

## 🔌 Configuração no cliente MCP

Exemplo para **Windows** (Claude Desktop, Cursor, VS Code, etc.):

```json
{
  "mcpServers": {
    "youtube-hunter": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\mcp\\youtube-hunter-mcp",
        "run",
        "youtube-hunter-mcp"
      ]
    }
  }
}
```

Em **macOS/Linux**, troque o caminho:

```json
{
  "mcpServers": {
    "youtube-hunter": {
      "command": "uv",
      "args": [
        "--directory",
        "/caminho/para/youtube-hunter-mcp",
        "run",
        "youtube-hunter-mcp"
      ]
    }
  }
}
```

> Se `uv` não estiver no `PATH` do cliente, use o caminho absoluto do executável.
> Os logs vão para `stderr`, então o JSON-RPC em `stdout` não é poluído.

---

## ⚙️ Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `YT_HUNTER_DOWNLOADS` | `<repo>/downloads` | Diretório base de thumbnails, screenshots, mines e relatórios. |
| `YT_HUNTER_TRANSCRIPT_CACHE` | `D:\mcp\youtube-hunter-mcp\downloads\transcripts_cache` | Cache de transcrições. **Defina explicitamente** se o projeto não estiver em `D:\mcp`. |
| `YT_HUNTER_COOKIES` | vazio | Caminho de um `cookies.txt` (formato Netscape) para yt-dlp e Innertube. |
| `YT_HUNTER_PROXY` | vazio | Proxy HTTP, ex.: `http://user:pass@host:port`. |
| `YT_HUNTER_TRANSCRIPT_CLIENTS` | `android_vr,tv,web_embedded,android,ios,mweb,web` | Player clients usados pelo `yt-dlp`. |
| `YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS` | `1500` | Intervalo mínimo entre chamadas de rede. |
| `YT_HUNTER_TRANSCRIPT_BLOCK_COOLDOWN_SEC` | `900` | Tempo de espera do circuit breaker após bloqueio. |
| `YT_HUNTER_MAX_CONCURRENT_BROWSERS` | `2` | Máximo de navegadores Playwright simultâneos. |
| `YT_HUNTER_TRANSCRIPT_API_URL` | vazio | Endpoint opcional da camada L5. |
| `YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE` | `false` | Se `true`, ignora o cache na leitura. |

---

## 📂 Dados gerados

Tudo é criado em tempo de execução e **não vai para o Git**:

| Diretório | Conteúdo |
|-----------|----------|
| `downloads/thumbnails/` | Capas em alta resolução, organizadas por canal/nicho. |
| `downloads/screenshots/` | Prints de páginas de busca, canais e vídeos. |
| `downloads/mines/` | JSONs brutos de minerações de canais e nichos. |
| `downloads/reports/` | Dashboards HTML gerados. |
| `downloads/transcripts_cache/` | Cache JSON de transcrições. |
| `dossiers/` | Dossiês Markdown compatíveis com Obsidian. |

---

## 🗂️ Estrutura do projeto

```text
youtube-hunter-mcp/
├── src/youtube_hunter_mcp/
│   ├── server.py              # FastMCP e as 14 tools
│   ├── browser.py             # Playwright: busca, canal, vídeo, screenshot
│   ├── channel_miner.py       # Mineração de canal e outliers
│   ├── niche_outliers.py      # Views x inscritos, OCR e hooks
│   ├── transcript.py          # Orquestração de transcrições
│   ├── transcript_sources.py  # Camadas L0–L5
│   ├── innertube_transcript.py# Camada L1B (get_panel)
│   ├── thumbnails.py          # Resolução e download de capas
│   ├── thumbnail_ocr.py       # OCR com RapidOCR/ONNX
│   ├── thumbnail_grid.py      # Moodboards de capas
│   ├── packaging_analyzer.py  # Título x capa
│   ├── pacing_analyzer.py     # WPM e loops de curiosidade
│   ├── dossier_generator.py   # Dossiês Markdown
│   ├── mining_report.py       # Catálogo e dashboard HTML
│   └── utils.py               # IDs, sanitização e helpers
├── scripts/                   # Verificações e rotinas de pesquisa
├── docs/TRANSCRIT.md          # Documentação do motor de transcrição
├── pyproject.toml
└── uv.lock
```

---

## 🧪 Verificação e testes

Os scripts de verificação usam o executável gerado em `.venv/Scripts/` (Windows). Rode `uv sync` antes.

```powershell
# Handshake MCP + lista das tools
uv run python scripts/verify_mcp_handshake.py

# Matriz de aceitação das camadas de transcrição
uv run python scripts/test_transcript_matrix.py

# Chamada real de yt_get_transcript pelo protocolo MCP
uv run python scripts/verify_tool_transcript.py
```

Para validar uma URL específica, use o próprio cliente MCP ou:

```powershell
uv run python -c "from youtube_hunter_mcp.transcript import get_video_transcript_async as g; import asyncio, json; print(json.dumps(asyncio.run(g('https://youtu.be/dQw4w9WgXcQ')), ensure_ascii=False)[:500])"
```

---

## ⚠️ Limitações conhecidas

- O scraping depende do DOM e das APIs internas do YouTube; mudanças de layout podem quebrar seletores.
- Bloqueios por IP e rate limit podem ocorrer. Configure `YT_HUNTER_COOKIES` e/ou `YT_HUNTER_PROXY`.
- O OCR baixa modelos na primeira execução e pode demorar; em máquinas modestas, reduza a concorrência.
- Alguns scripts em `scripts/` são rotinas históricas de pesquisa e podem referenciar caminhos antigos.
- Transcrições muito longas e minerações grandes podem gerar respostas extensas; para uso com agentes, prefira limites menores de `max_videos` e `enrich_top_n`.

---

## 📄 Documentação adicional

- [`docs/TRANSCRIT.md`](docs/TRANSCRIT.md) — arquitetura, camadas, cookies, proxy e diagnóstico do motor de transcrição.
- [`DOCUMENTACAO.md`](DOCUMENTACAO.md) — visão funcional e exemplos de uso (pode conter referências a versões anteriores).

---

Feito para pesquisa de conteúdo e inteligência competitiva no YouTube.
