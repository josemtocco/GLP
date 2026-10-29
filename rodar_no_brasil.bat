@echo off
REM ============================================================
REM  Gera a playlist.m3u do Globoplay a partir do SEU PC (Brasil)
REM  Rode este arquivo com um duplo-clique.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

REM --- Credenciais (preencha uma das opcoes) -------------------
REM Opcao A: email e senha da sua conta Globo
set "GLOBO_EMAIL="
set "GLOBO_PASSWORD="
REM Opcao B: cookie GLBID ja autenticado (F12 -> Application -> Cookies)
set "GLBID="

REM --- Opcoes --------------------------------------------------
REM set "INCLUDE_DRM=0"   REM descomente para excluir canais com DRM
REM set "GLOBO_DEBUG=1"   REM descomente para log detalhado

where python >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Python nao encontrado. Instale do python.org e marque
  echo        "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Gerando playlist.m3u ...
python gerar_globoplay.py %*

echo.
echo Pronto. Veja playlist.m3u nesta pasta.
pause
