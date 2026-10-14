@echo off
title Baixador de Musicas
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

:: So encontra o Python e abre a janela (app.py).
:: spotDL, FFmpeg e Deno sao instalados pela propria janela no primeiro download.

for %%F in (app.py metadata_fallback.py) do (
    if not exist "%%F" (
        echo [ERRO] O arquivo %%F nao foi encontrado. Ele precisa ficar na mesma pasta deste .bat.
        pause
        exit /b
    )
)

:: "py -3" primeiro; "python" pode ser so o atalho falso da Microsoft Store.
set "PYCMD=py -3"
%PYCMD% -c "print(1)" >nul 2>&1
if %errorlevel% equ 0 goto CHECK_TKINTER
set "PYCMD=python"
%PYCMD% -c "print(1)" >nul 2>&1
if %errorlevel% equ 0 goto CHECK_TKINTER
goto INSTALL_PYTHON

:CHECK_TKINTER
%PYCMD% -c "import tkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Este Python nao tem o Tkinter, necessario para a janela.
    echo Reinstale o Python marcando a opcao "tcl/tk and IDLE".
    pause
    exit /b
)

:: pythonw.exe abre a janela sem deixar um terminal aberto atras dela.
set "PYW="
for /f "usebackq delims=" %%i in (`%PYCMD% -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"`) do set "PYW=%%i"
if exist "!PYW!" (
    start "" "!PYW!" app.py
) else (
    start "" %PYCMD% app.py
)
exit /b

:INSTALL_PYTHON
echo [AVISO] O Python nao foi encontrado.
set /p install_py="Deseja instalar o Python automaticamente agora? (S/N): "
if /i not "%install_py%"=="S" exit /b
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Nao foi possivel instalar automaticamente.
    echo Instale pelo site https://www.python.org/downloads/
    echo Se digitar "python" abrir a Microsoft Store, desative "python.exe" em:
    echo Configuracoes ^> Aplicativos ^> Configuracoes avancadas ^> Aliases de execucao do aplicativo
    pause
    exit /b
)
echo.
echo [OK] Python instalado. Feche esta janela e abra o .bat de novo.
pause
