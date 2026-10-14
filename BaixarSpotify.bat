@echo off
chcp 65001 >nul
title Baixador de Musicas
color 0A
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Este .bat so prepara o ambiente e abre a janela (app.py).
:: Obs.: em "echo", os sinais ">" precisam ser escritos como "^>",
:: senao o Windows entende como redirecionamento para arquivo.

echo ==========================================================
echo        BAIXADOR DE MUSICAS - PREPARANDO O APLICATIVO
echo ==========================================================
echo.

:: ==========================================================
:: CHECAGEM DE PYTHON (com correcao do "alias falso" da Store)
:: ==========================================================
:CHECK_PYTHON
echo [^>^>] Verificando Python...

set "PYCMD="

:: 1) Tenta primeiro o "py launcher", que nao sofre do bug do alias da Store
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYCMD=py -3"
    echo [OK] Python encontrado via launcher "py".
    goto CHECK_FILES
)

:: 2) Tenta o comando "python" normal
python --version >nul 2>&1
if %errorlevel% neq 0 goto INSTALL_PYTHON

:: 3) Confirma que "python" nao eh o alias falso da Microsoft Store
python -c "print(1)" >nul 2>&1
if %errorlevel% neq 0 goto FIX_FAKE_ALIAS

set "PYCMD=python"
echo [OK] Python encontrado e funcionando.
goto CHECK_FILES

:FIX_FAKE_ALIAS
echo.
echo [AVISO] Foi detectado o "Alias de Execucao de Aplicativo" falso do
echo Python, criado pelo Windows. Ele finge que o Python existe, mas
echo so abre a Microsoft Store quando voce tenta usa-lo.
echo.
call :ENSURE_WINGET || exit /b
echo [^>^>] Instalando o Python real via winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Nao foi possivel instalar automaticamente.
    echo Corrija manualmente assim:
    echo  1^) Configuracoes ^> Aplicativos ^> Configuracoes avancadas do aplicativo
    echo  2^) Abra "Aliases de execucao do aplicativo"
    echo  3^) DESATIVE "python.exe" e "python3.exe"
    echo  4^) Abra este script novamente
    pause
    exit /b
)
echo.
echo [IMPORTANTE] Python real instalado!
echo Feche esta janela e abra o script novamente para recarregar o PATH.
pause
exit /b

:INSTALL_PYTHON
echo.
echo [AVISO] Python nao foi encontrado no seu sistema.
echo O Python e necessario para executar o aplicativo.
set /p install_py="Deseja instalar o Python automaticamente agora? (S/N): "
if /i "%install_py%" neq "S" (
    echo [ERRO FATAL] Nao e possivel continuar sem o Python.
    pause
    exit /b
)
call :ENSURE_WINGET || exit /b
echo.
echo Instalando Python via winget. Isso pode levar alguns minutos...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao tentar instalar o Python. Instale-o manualmente.
    pause
    exit /b
)
echo.
echo [IMPORTANTE] O Python foi instalado com sucesso!
echo Feche esta janela e abra o script novamente para recarregar o PATH.
pause
exit /b

:: ==========================================================
:: ARQUIVOS DO APLICATIVO E TKINTER (janela)
:: ==========================================================
:CHECK_FILES
for %%F in (app.py metadata_fallback.py) do (
    if not exist "%SCRIPT_DIR%%%F" (
        echo [ERRO] O arquivo %%F nao foi encontrado.
        echo Ele precisa ficar na mesma pasta deste .bat.
        pause
        exit /b
    )
)

%PYCMD% -c "import tkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Este Python nao tem o Tkinter, necessario para a janela.
    echo Reinstale o Python marcando a opcao "tcl/tk and IDLE".
    pause
    exit /b
)

:: ==========================================================
:: CHECAGEM DE SPOTDL E MUTAGEN (so instala se faltar)
:: ==========================================================
:CHECK_SPOTDL
echo [^>^>] Verificando spotDL e Mutagen...
%PYCMD% -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('spotdl') and u.find_spec('mutagen') else 1)" >nul 2>&1
if %errorlevel% equ 0 goto SPOTDL_OK
echo [^>^>] Instalando spotDL e ferramentas do YouTube pela primeira vez...
echo [^>^>] Isso pode demorar alguns minutos. Acompanhe o progresso abaixo:
echo.
%PYCMD% -m pip install -U spotdl yt-dlp ytmusicapi brotli websockets mutagen
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha ao instalar o spotDL.
    echo Tente executar este script novamente como administrador.
    pause
    exit /b
)
:SPOTDL_OK
echo [OK] spotDL pronto. Para atualizar, use o botao "Atualizar ferramentas" na janela.

:: ==========================================================
:: CHECAGEM DE FFMPEG
:: ==========================================================
:CHECK_FFMPEG
echo [^>^>] Verificando FFmpeg...
set "PATH=%PATH%;C:\ffmpeg\bin"
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 goto FFMPEG_OK
if exist "%USERPROFILE%\.spotdl\ffmpeg.exe" goto FFMPEG_OK

echo [^>^>] FFmpeg nao encontrado. Baixando pelo spotDL...
%PYCMD% -m spotdl --download-ffmpeg
if exist "%USERPROFILE%\.spotdl\ffmpeg.exe" goto FFMPEG_OK

echo.
echo [AVISO] O spotDL nao conseguiu baixar o FFmpeg.
echo O FFmpeg e necessario para converter o audio e embutir capas.
set /p install_ff="Deseja instalar o FFmpeg pelo winget agora? (S/N): "
if /i "%install_ff%" neq "S" (
    echo [ERRO FATAL] Nao e possivel continuar sem o FFmpeg.
    pause
    exit /b
)
call :ENSURE_WINGET || exit /b
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao tentar instalar o FFmpeg. Instale-o manualmente.
    pause
    exit /b
)
echo.
echo [IMPORTANTE] O FFmpeg foi instalado com sucesso!
echo Feche esta janela e abra o script novamente para recarregar o PATH.
pause
exit /b

:FFMPEG_OK
echo [OK] FFmpeg encontrado.

:: ==========================================================
:: CHECAGEM DE DENO (ajuda o yt-dlp com o YouTube)
:: ==========================================================
:CHECK_DENO
echo [^>^>] Verificando Deno...
where deno >nul 2>&1
if %errorlevel% equ 0 goto DENO_OK
if exist "%USERPROFILE%\.spotdl\deno.exe" goto DENO_OK

echo [^>^>] Deno nao encontrado. Baixando pelo spotDL...
%PYCMD% -m spotdl --download-deno
if exist "%USERPROFILE%\.spotdl\deno.exe" goto DENO_OK

echo [^>^>] Tentando instalar o Deno via winget...
where winget >nul 2>&1
if %errorlevel% equ 0 (
    winget install -e --id DenoLand.Deno --accept-package-agreements --accept-source-agreements
)
echo [AVISO] Se o Deno ainda nao for encontrado, algumas musicas do YouTube podem falhar.
echo Instale manualmente em https://deno.com se isso acontecer.
goto ABRIR_JANELA

:DENO_OK
echo [OK] Deno encontrado.

:: ==========================================================
:: ABRE A JANELA DO APLICATIVO
:: ==========================================================
:ABRIR_JANELA
echo.
echo [^>^>] Abrindo a janela do aplicativo...

:: pythonw.exe abre a janela sem deixar um terminal aberto atras dela.
set "PYW="
for /f "usebackq delims=" %%i in (`%PYCMD% -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYW=%%i"

if defined PYW if exist "!PYW!" (
    start "" "!PYW!" "%SCRIPT_DIR%app.py"
    exit /b
)
start "" %PYCMD% "%SCRIPT_DIR%app.py"
exit /b

:: ==========================================================
:: SUB-ROTINAS
:: ==========================================================
:ENSURE_WINGET
where winget >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] O winget nao foi encontrado neste Windows.
    echo Instale a dependencia manualmente e abra o script novamente.
    pause
    exit /b 1
)
exit /b 0
