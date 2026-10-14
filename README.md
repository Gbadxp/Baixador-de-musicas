# Baixador de Musicas

Aplicativo com janela para Windows que automatiza downloads com o `spotDL`.

O fluxo principal e:

- links do Spotify fornecem nome da musica, artista, album, ano, capa e outros metadados;
- o audio e buscado pelo `spotDL` em fontes como YouTube/YouTube Music;
- os arquivos finais sao salvos em MP3 com tags ID3, capa embutida e relatorio de verificacao;
- se alguma tag ou capa ficar faltando, o app tenta pesquisar metadados diretamente na internet.

> Importante: o app nao extrai audio diretamente do Spotify. Ele usa o Spotify como fonte de metadados e o YouTube como fonte provavel do audio.

## Funcionalidades

- Janela simples: cole o link, clique em **Baixar** e acompanhe a barra de progresso.
- Botoes para colar o link, escolher onde salvar, cancelar o download e abrir a pasta no final.
- Verifica e instala Python, FFmpeg, spotDL, Mutagen e Deno quando necessario.
- Detecta links do Spotify e do YouTube.
- Cria pastas sequenciais por download: `Musicas_Spotify`, `Musicas_Spotify_2`, `Musicas_YouTube`, etc.
- Usa YouTube normal primeiro e YouTube Music como reserva.
- Se alguma musica falhar, atualiza `spotDL`/`yt-dlp` e tenta de novo automaticamente.
- Valida se os MP3 baixados possuem capa embutida.
- Pesquisa metadados incompletos no iTunes Search e no MusicBrainz (capas do Cover Art Archive).
- Musicas sem capa ganham uma segunda tentativa de download, mas **nunca sao apagadas**: se a nova tentativa nao trouxer a musica, o arquivo original volta para a pasta.
- Deixa so o artista principal no campo `artist` e preenche `albumartist` para melhorar a compatibilidade com Apple Music/iPhone, sem quebrar nomes como `AC/DC` ou `Tyler, The Creator`.
- Gera `metadata_report.txt` e `download_log.txt` (com a saida completa do spotDL) dentro da pasta criada.

## Como usar

1. Deixe `BaixarSpotify.bat`, `app.py` e `metadata_fallback.py` na mesma pasta.
2. Execute `BaixarSpotify.bat` com dois cliques.
3. Na primeira vez, aguarde a instalacao das dependencias no terminal.
4. A janela do aplicativo abre automaticamente.
5. Cole um link de musica, album ou playlist do Spotify (ou do YouTube) e clique em **Baixar**.
6. Quando terminar, clique em **Abrir pasta**.

Se o Python ja estiver instalado, tambem da para abrir a janela direto com `pythonw app.py`.

## Arquivos

| Arquivo | Funcao |
| --- | --- |
| `BaixarSpotify.bat` | Verifica/instala as dependencias e abre a janela |
| `app.py` | Janela do aplicativo (Tkinter, ja vem com o Python) |
| `metadata_fallback.py` | Confere capas e tags e busca o que faltar na internet |

## Estrutura gerada

```text
Musicas_Spotify/
  Artista - Musica.mp3
  metadata_report.txt
  download_log.txt

Musicas_Spotify_2/
  ...

Musicas_YouTube/
  ...
```

## Dependencias

O `.bat` instala o que faltar. O spotDL so e instalado na primeira vez; para atualizar depois, use o botao **Atualizar ferramentas** na janela (o app tambem atualiza sozinho quando um download falha).

| Dependencia | Finalidade |
| --- | --- |
| Python (com Tkinter) | Executar o app, o spotDL e o verificador de tags |
| FFmpeg | Converter audio e embutir capas (baixado pelo spotDL ou via `winget`) |
| spotDL | Resolver links, baixar musicas e aplicar metadados |
| Mutagen | Validar e ajustar tags ID3 |
| Deno | Auxiliar downloads do YouTube em alguns casos |
| yt-dlp, ytmusicapi, brotli, websockets | Baixar audio do YouTube e evitar erros comuns de extracao |

## Erro "Could not get client token"

Esse erro vem do lado do YouTube/YouTube Music, nao do Spotify. O app tenta evitar isso de tres formas:

1. Usa `--audio youtube youtube-music`, ou seja, tenta YouTube normal antes de YouTube Music.
2. Se alguma musica falhar, atualiza automaticamente `spotDL`, `yt-dlp`, `ytmusicapi`, `brotli` e `websockets`.
3. Depois do reparo, tenta baixar de novo (as musicas que ja foram baixadas sao puladas).

Se ainda aparecer erro de login, bot, cookie ou PO token, significa que o YouTube bloqueou aquela sessao. Nesse caso, normalmente resolve tentando mais tarde; em casos persistentes, pode ser necessario usar cookies do navegador com o `spotDL` (`--cookie-file`).

## Busca online de metadados

Quando o arquivo MP3 fica sem `title`, `artist`, `album` ou capa, o `metadata_fallback.py` tenta:

1. Buscar a faixa no iTunes Search e preencher tags/capa quando encontrar uma correspondencia boa (titulo e artista sao comparados separadamente).
2. Buscar no MusicBrainz se o iTunes nao retornar um resultado confiavel, com a capa vinda do Cover Art Archive.
3. Registrar tudo em `metadata_report.txt`.

Se a capa ainda nao for encontrada, a musica e separada temporariamente em `_sem_capa_aguardando` e o `spotDL` faz uma segunda tentativa. Na verificacao final nada e removido: o que nao foi baixado de novo volta para a pasta e aparece no relatorio como `SEM CAPA (mantido)`.

O verificador tambem funciona sozinho pelo terminal:

```text
python metadata_fallback.py "Musicas_Spotify"          # 1a passada
python metadata_fallback.py "Musicas_Spotify" --final  # depois da nova tentativa
```

## Aviso legal

Use apenas com conteudo que voce tenha direito de baixar. Baixar ou redistribuir obras protegidas sem autorizacao pode violar termos de uso de plataformas e leis de direitos autorais.
