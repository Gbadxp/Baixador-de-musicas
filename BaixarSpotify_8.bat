@echo off
chcp 65001 >nul
title Baixar Musicas com Metadados
color 0A
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ==========================================================
echo        VERIFICACAO DE DEPENDENCIAS E PRE-REQUISITOS
echo ==========================================================
echo.

:: ==========================================================
:: CHECAGEM DE PYTHON (com correcao do "alias falso" da Store)
:: ==========================================================
:CHECK_PYTHON
echo [>>] Verificando Python...

set "PYCMD="

:: 1) Tenta primeiro o "py launcher", que nao sofre do bug do alias da Store
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYCMD=py -3"
    echo [OK] Python encontrado via launcher "py".
    goto CHECK_FFMPEG
)

:: 2) Tenta o comando "python" normal
python --version >nul 2>&1
if %errorlevel% neq 0 goto INSTALL_PYTHON

:: 3) Confirma que "python" nao eh o alias falso da Microsoft Store
python -c "print(1)" >nul 2>&1
if %errorlevel% neq 0 goto FIX_FAKE_ALIAS

set "PYCMD=python"
echo [OK] Python encontrado e funcionando.
goto CHECK_FFMPEG

:FIX_FAKE_ALIAS
echo.
echo [AVISO] Foi detectado o "Alias de Execucao de Aplicativo" falso do
echo Python, criado pelo Windows. Ele finge que o Python existe, mas
echo so abre a Microsoft Store quando voce tenta usa-lo.
echo.
call :ENSURE_WINGET || exit /b
echo [>>] Instalando o Python real via winget...
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
echo O Python e necessario para executar o spotDL.
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
:: CHECAGEM DE FFMPEG
:: ==========================================================
:CHECK_FFMPEG
echo [>>] Verificando FFmpeg...
set "PATH=%PATH%;C:\ffmpeg\bin"
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 goto INSTALL_FFMPEG
echo [OK] FFmpeg encontrado.
goto CHECK_SPOTDL

:INSTALL_FFMPEG
echo.
echo [AVISO] O FFmpeg nao foi encontrado!
echo O FFmpeg e necessario para converter o audio e embutir capas.
set /p install_ff="Deseja instalar o FFmpeg automaticamente agora? (S/N): "
if /i "%install_ff%" neq "S" (
    echo [ERRO FATAL] Nao e possivel continuar sem o FFmpeg.
    pause
    exit /b
)
call :ENSURE_WINGET || exit /b
echo.
echo Instalando FFmpeg via winget. Isso pode levar alguns minutos...
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

:: ==========================================================
:: CHECAGEM DE SPOTDL E MUTAGEN
:: ==========================================================
:CHECK_SPOTDL
echo [>>] Verificando spotDL...
%PYCMD% -m pip show spotdl >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [>>] spotDL nao foi encontrado. Instalando pela primeira vez...
    echo [>>] Isso pode demorar alguns minutos. Acompanhe o progresso abaixo:
    echo.
    %PYCMD% -m pip install -U spotdl
    if errorlevel 1 (
        echo.
        echo [ERRO] Falha ao instalar o spotDL.
        pause
        exit /b
    )
) else (
    echo [OK] spotDL pronto.
)

echo [>>] Atualizando ferramentas de download do YouTube...
echo [>>] Isso corrige erros comuns do yt-dlp, como "Could not get client token".
%PYCMD% -m pip install -U spotdl yt-dlp ytmusicapi brotli websockets mutagen
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao atualizar spotDL/yt-dlp.
    echo Tente executar este script novamente como administrador.
    pause
    exit /b
)
echo [OK] Ferramentas de download atualizadas.

echo [>>] Verificando biblioteca de metadados...
%PYCMD% -c "import mutagen" >nul 2>&1
if %errorlevel% neq 0 (
    echo [>>] Instalando Mutagen para validar capas e tags...
    %PYCMD% -m pip install -U mutagen
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar o Mutagen.
        pause
        exit /b
    )
)
echo [OK] Validador de metadados pronto.
echo.
if not exist "%SCRIPT_DIR%metadata_fallback.py" (
    echo [ERRO] O arquivo metadata_fallback.py nao foi encontrado.
    echo Ele precisa ficar na mesma pasta deste .bat.
    pause
    exit /b
)

:: ==========================================================
:: CHECAGEM DE DENO
:: ==========================================================
:CHECK_DENO
echo [>>] Verificando Deno...
where deno >nul 2>&1
if %errorlevel% neq 0 goto INSTALL_DENO
echo [OK] Deno encontrado.
goto FIM_CHECAGENS

:INSTALL_DENO
echo.
echo [AVISO] O Deno nao foi encontrado!
echo O Deno ajuda o spotDL a baixar algumas musicas usando YouTube.
echo.
echo Instalando Deno automaticamente via spotDL...
%PYCMD% -m spotdl --download-deno
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha ao instalar o Deno automaticamente pelo spotDL.
    echo Tentando instalar via winget...
    call :ENSURE_WINGET || exit /b
    winget install -e --id DenoLand.Deno --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel instalar o Deno. Instale manualmente em https://deno.com
        pause
        exit /b
    )
    echo.
    echo [IMPORTANTE] O Deno foi instalado com sucesso!
    echo Feche esta janela e abra o script novamente para recarregar o PATH.
    pause
    exit /b
)
echo [OK] Deno instalado com sucesso.

:FIM_CHECAGENS
echo.
goto INICIO

:: ==========================================================
:: INICIO DO SCRIPT PRINCIPAL
:: ==========================================================
:INICIO
cls
echo ==========================================================
echo       BAIXAR MUSICAS COM METADADOS COMPLETOS (MP3)
echo ==========================================================
echo.
echo Spotify: usa o link para metadados e busca o audio no YouTube.
echo YouTube : baixa pelo YouTube; os metadados podem variar por video.
echo.
echo Cole um link de musica, album ou playlist.
echo Para sair, feche esta janela.
echo.

set "url="
set /p url="Link: "
set "url=%url:"=%"

if "%url%"=="" goto INICIO

call :DETECT_LINK_TYPE "%url%"
if "%LINK_KIND%"=="generico" (
    echo.
    echo [AVISO] O link nao parece ser do Spotify nem do YouTube.
    set /p continue_unknown="Deseja tentar mesmo assim? (S/N): "
    if /i not "!continue_unknown!"=="S" goto INICIO
)

if "%LINK_KIND%"=="spotify" (
    set "folder_base=Musicas_Spotify"
    echo.
    echo [INFO] Link do Spotify detectado.
    echo [INFO] Os metadados virao do Spotify. O audio sera buscado no YouTube.
) else if "%LINK_KIND%"=="youtube" (
    set "folder_base=Musicas_YouTube"
    echo.
    echo [INFO] Link do YouTube detectado.
    echo [INFO] Os metadados dependem do que o spotDL conseguir identificar.
) else (
    set "folder_base=Musicas_Baixadas"
)

echo.
echo [>>] Preparando pasta de destino...
call :CREATE_FOLDER "%folder_base%"
if %errorlevel% neq 0 (
    echo [ERRO] Nao foi possivel criar a pasta de destino.
    pause
    goto INICIO
)
echo [OK] Pasta criada: "%folder%"

pushd "%folder%" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Nao foi possivel acessar a pasta de destino.
    pause
    goto INICIO
)

echo.
echo [>>] Baixando e aplicando metadados...
echo [>>] Usando YouTube normal primeiro e YouTube Music como reserva.
echo [>>] Aguarde. Playlists grandes podem demorar bastante.
echo [INFO] O detalhe tecnico fica em "download_log.txt" dentro da pasta criada.
echo.

call :RUN_SPOTDL "%url%"
if errorlevel 1 (
    echo.
    echo [AVISO] O download falhou. Vou reparar yt-dlp/YouTube e tentar novamente.
    echo [DICA] Esse reparo costuma resolver "Could not get client token".
    echo.
    call :REPAIR_YOUTUBE_TOOLS
    if errorlevel 1 (
        popd
        echo.
        echo [ERRO] Nao foi possivel reparar as ferramentas de download.
        pause
        goto INICIO
    )
    echo.
    echo [>>] Tentando baixar novamente...
    call :RUN_SPOTDL "%url%"
    if errorlevel 1 (
        popd
        echo.
        echo [ERRO] Ocorreu um problema ao baixar mesmo apos o reparo.
        echo Veja o arquivo "download_log.txt" dentro da pasta criada.
        echo.
        echo Se o erro citar login, bot ou PO token, o YouTube bloqueou a sessao.
        echo Nesse caso sera preciso tentar mais tarde ou usar cookies do navegador.
        echo.
        pause
        goto INICIO
    )
)

echo.
echo [>>] Validando capas, artistas e tags ID3...
%PYCMD% "%SCRIPT_DIR%metadata_fallback.py"
set "meta_result=%errorlevel%"

if "%meta_result%"=="1" (
    echo.
    echo [AVISO] Alguma musica veio sem capa embutida.
    echo [>>] Fazendo uma segunda tentativa automatica...
    echo.
    call :RUN_SPOTDL "%url%"
    echo.
    echo [>>] Validando novamente...
    %PYCMD% "%SCRIPT_DIR%metadata_fallback.py"
    set "meta_result=!errorlevel!"
)

popd

echo.
echo ==========================================================
echo                     CONCLUIDO!
echo ==========================================================
echo As musicas foram salvas em:
echo "%folder%"
echo.
if "%meta_result%"=="0" (
    echo Metadados verificados: capas e tags principais OK.
) else (
    echo Algumas musicas ainda podem estar sem capa ou com metadados incompletos.
    echo Veja o arquivo "metadata_report.txt" dentro da pasta criada.
)
echo.
echo Pressione qualquer tecla para baixar outra musica...
pause >nul
goto INICIO

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

:DETECT_LINK_TYPE
set "LINK_KIND=generico"
echo("%~1"| findstr /i /c:"open.spotify.com" /c:"spotify:" >nul 2>&1
if %errorlevel% equ 0 (
    set "LINK_KIND=spotify"
    exit /b 0
)
echo("%~1"| findstr /i /c:"youtube.com" /c:"youtu.be" /c:"music.youtube.com" >nul 2>&1
if %errorlevel% equ 0 (
    set "LINK_KIND=youtube"
    exit /b 0
)
exit /b 0

:CREATE_FOLDER
set "basename=%~1"
set "folder=%SCRIPT_DIR%%basename%"
set "count=1"

:CREATE_FOLDER_LOOP
if exist "%folder%" (
    set /a count+=1
    set "folder=%SCRIPT_DIR%%basename%_%count%"
    goto CREATE_FOLDER_LOOP
)
mkdir "%folder%" >nul 2>&1
exit /b %errorlevel%

:RUN_SPOTDL
echo ==========================================================>> "download_log.txt"
echo Nova tentativa: %date% %time%>> "download_log.txt"
echo Comando: spotdl download "%~1" --audio youtube youtube-music>> "download_log.txt"
%PYCMD% -m spotdl download "%~1" --audio youtube youtube-music --format mp3 --threads 4 --max-retries 5 >> "download_log.txt" 2>&1
exit /b %errorlevel%

:REPAIR_YOUTUBE_TOOLS
%PYCMD% -m pip install -U spotdl yt-dlp ytmusicapi brotli websockets mutagen
if errorlevel 1 exit /b 1
%PYCMD% -m spotdl --download-deno
exit /b %errorlevel%
