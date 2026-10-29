# Baixador de Musicas

Aplicativo com janela para Windows que baixa musicas, albuns e playlists com o `spotDL`.

- Links do Spotify ou do Apple Music fornecem os metadados (nome, artista, album, ano, capa).
- O audio e buscado no YouTube/YouTube Music.
- Os arquivos sao salvos em MP3 de 320 kbps com tags ID3 e capa embutida.

> O app nao extrai audio do Spotify nem do Apple Music: eles sao so a fonte dos metadados e o YouTube e a fonte do audio.

## Como usar

1. Deixe `BaixarSpotify.bat`, `app.py`, `metadata_fallback.py` e `apple_music.py` na mesma pasta.
2. De dois cliques em `BaixarSpotify.bat` (se o Python nao estiver instalado, ele oferece instalar).
3. Na janela, cole o link de uma musica, album ou playlist do Spotify, do Apple Music (ou do YouTube) e clique em **Baixar**.
4. Quando terminar, clique em **Abrir pasta**.

No primeiro download a janela instala sozinha o spotDL, o FFmpeg e o Deno.

## Arquivos

| Arquivo | Funcao |
| --- | --- |
| `BaixarSpotify.bat` | Encontra o Python e abre a janela |
| `app.py` | Janela: instala as ferramentas, baixa e mostra o progresso |
| `apple_music.py` | Le as musicas de links do Apple Music (API publica da Apple) |
| `metadata_fallback.py` | Confere capas e tags e busca o que faltar na internet |

Cada download ganha uma pasta nova (`Musicas_Spotify`, `Musicas_AppleMusic`, `Musicas_YouTube`...) com os MP3, o `metadata_report.txt`, o `download_log.txt` (saida completa do spotDL) e, se alguma musica falhar, o `musicas_que_falharam.txt`.

## Como funciona

- Usa YouTube primeiro e YouTube Music como reserva.
- Links do Apple Music: as musicas sao lidas pela API publica da Apple (playlists precisam ser publicas). Titulo, artista, album, capa e duracao vem da Apple e o spotDL so busca o audio no YouTube.
- Se alguma musica falhar por erro temporario, atualiza `spotDL`/`yt-dlp` e tenta de novo; as que ja foram baixadas sao puladas. O botao **Atualizar ferramentas** faz essa atualizacao manualmente.
- Se faltar titulo, artista, album ou capa, busca no iTunes Search e depois no MusicBrainz (capas do Cover Art Archive).
- Musicas que continuam sem capa ganham uma nova tentativa de download, mas **nunca sao apagadas**: se a nova tentativa nao trouxer a musica, o arquivo original volta para a pasta.
- Deixa so o artista principal no campo `artist` e preenche `albumartist` (melhor no Apple Music/iPhone), sem quebrar nomes como `AC/DC` ou `Tyler, The Creator`.

## Qualidade do audio (e por que nao ha lossless/Dolby Atmos)

O audio vem do YouTube, que entrega no maximo cerca de 128-160 kbps (Opus/AAC). O app salva em MP3 de 320 kbps para nao perder ainda mais qualidade na conversao, mas isso nao deixa o som melhor que a fonte. Converter para FLAC ou WAV tambem nao: o arquivo fica maior com a mesma qualidade.

Lossless e Dolby Atmos do Apple Music, Tidal ou Amazon Music sao protegidos por DRM, e tirar o audio de la exigiria quebrar essa protecao, o que o app nao faz. Para ter arquivos lossless de verdade, compre em lojas que vendem sem DRM (como Bandcamp ou Qobuz). Dolby Atmos, na pratica, so e ouvido dentro dos proprios apps de streaming.

## Erros do YouTube

Erros como login, bot, cookie ou PO token vem do YouTube. O app ja atualiza as ferramentas e tenta de novo automaticamente. Se continuar, o YouTube bloqueou a sessao: normalmente resolve tentando mais tarde. Videos com restricao de idade exigem login no YouTube e aparecem na lista de falhas.

## Aviso legal

Use apenas com conteudo que voce tenha direito de baixar. Baixar ou redistribuir obras protegidas sem autorizacao pode violar termos de uso de plataformas e leis de direitos autorais.
