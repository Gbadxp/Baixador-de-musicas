# Baixador de Musicas

Aplicativo com janela para Windows que baixa musicas, albuns e playlists com o `spotDL`.

- Links do Spotify fornecem os metadados (nome, artista, album, ano, capa).
- O audio e buscado no YouTube/YouTube Music.
- Os arquivos sao salvos em MP3 com tags ID3 e capa embutida.

> O app nao extrai audio do Spotify: o Spotify e so a fonte dos metadados e o YouTube e a fonte do audio.

## Como usar

1. Deixe `BaixarSpotify.bat`, `app.py` e `metadata_fallback.py` na mesma pasta.
2. De dois cliques em `BaixarSpotify.bat` (se o Python nao estiver instalado, ele oferece instalar).
3. Na janela, cole o link de uma musica, album ou playlist do Spotify (ou do YouTube) e clique em **Baixar**.
4. Quando terminar, clique em **Abrir pasta**.

No primeiro download a janela instala sozinha o spotDL, o FFmpeg e o Deno.

## Arquivos

| Arquivo | Funcao |
| --- | --- |
| `BaixarSpotify.bat` | Encontra o Python e abre a janela |
| `app.py` | Janela: instala as ferramentas, baixa e mostra o progresso |
| `metadata_fallback.py` | Confere capas e tags e busca o que faltar na internet |

Cada download ganha uma pasta nova (`Musicas_Spotify`, `Musicas_Spotify_2`, `Musicas_YouTube`...) com os MP3, o `metadata_report.txt` e o `download_log.txt` (saida completa do spotDL).

## Como funciona

- Usa YouTube primeiro e YouTube Music como reserva.
- Se alguma musica falhar, atualiza `spotDL`/`yt-dlp` e tenta de novo; as que ja foram baixadas sao puladas. O botao **Atualizar ferramentas** faz essa atualizacao manualmente.
- Se faltar titulo, artista, album ou capa, busca no iTunes Search e depois no MusicBrainz (capas do Cover Art Archive).
- Musicas que continuam sem capa ganham uma nova tentativa de download, mas **nunca sao apagadas**: se a nova tentativa nao trouxer a musica, o arquivo original volta para a pasta.
- Deixa so o artista principal no campo `artist` e preenche `albumartist` (melhor no Apple Music/iPhone), sem quebrar nomes como `AC/DC` ou `Tyler, The Creator`.

## Erros do YouTube

Erros como "Could not get client token", login, bot, cookie ou PO token vem do YouTube, nao do Spotify. O app ja atualiza as ferramentas e tenta de novo automaticamente. Se continuar, o YouTube bloqueou a sessao: normalmente resolve tentando mais tarde.

## Aviso legal

Use apenas com conteudo que voce tenha direito de baixar. Baixar ou redistribuir obras protegidas sem autorizacao pode violar termos de uso de plataformas e leis de direitos autorais.
