@echo off
REM Inicia o bgutil-ytdlp-pot-provider (PO Token) local na porta 4416.
REM Uso:  scripts\start_pot_provider.cmd
REM
REM O provider e OPCIONAL: a camada L1B (Innertube get_panel) resolve a
REM transcricao sem PO Token.  Ele serve para baixar midia (formatos de video)
REM e para scenarios em que o IP nao esta penalizado pelo YouTube.

setlocal
set SERVER_DIR=D:\mcp\youtube-hunter-mcp\.tools\bgutil-pot\repo\server
set PORT=4416

if not exist "%SERVER_DIR%\dist\main.js" (
    echo [POT] Compilando o servidor...
    pushd "%SERVER_DIR%"
    call npx tsc --outDir dist
    popd
)

echo [POT] Subindo bgutil POT provider em http://127.0.0.1:%PORT%
pushd "%SERVER_DIR%"
start "" /b node dist\main.js --port %PORT%
popd

timeout /t 6 /nobreak >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%PORT%/ping' -TimeoutSec 8; Write-Host ('[POT] OK: ' + $r.Content) } catch { Write-Host '[POT] FALHOU ao subir o provider' }"
endlocal
