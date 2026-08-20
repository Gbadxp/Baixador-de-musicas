# BaixarSpotify.bat

Script em Batch para Windows que automatiza downloads com o `spotDL`.

O fluxo principal e:

- links do Spotify fornecem nome da musica, artista, album, ano, capa e outros metadados;
- o audio e buscado pelo `spotDL` em fontes como YouTube/YouTube Music;
- os arquivos finais sao salvos em MP3 com tags ID3, capa embutida e relatorio de verificacao;
- se alguma tag ou capa ficar faltando, o app tenta pesquisar metadados diretamente na internet.

> Importante: o script nao extrai audio diretamente do Spotify. Ele usa o Spotify como fonte de metadados e o YouTube como fonte provavel do audio.

## Funcionalidades

- Verifica e instala Python, FFmpeg, spotDL, Mutagen e Deno quando necessario.
- Detecta links do Spotify e do YouTube.
- Cria pastas sequenciais por sessao: `Musicas_Spotify`, `Musicas_Spotify_2`, `Musicas_YouTube`, etc.
- Valida se os MP3 baixados possuem capa embutida.
- Pesquisa metadados incompletos no iTunes Search e no MusicBrainz.
- Remove musicas sem capa e faz uma segunda tentativa automatica.
- Normaliza o campo `artist` e preenche `albumartist` para melhorar compatibilidade com Apple Music/iPhone.
- Gera `metadata_report.txt` dentro da pasta criada.

## Como usar

1. Deixe `BaixarSpotify_8.bat` e `metadata_fallback.py` na mesma pasta.
2. Execute `BaixarSpotify_8.bat` com dois cliques.
3. Aguarde a verificacao das dependencias.
4. Cole um link de musica, album ou playlist do Spotify.
5. Tambem e possivel colar links do YouTube, mas os metadados podem variar.
6. Aguarde o download terminar.
7. Confira os arquivos na pasta criada automaticamente.

## Estrutura gerada

```text
Musicas_Spotify/
  Artista - Musica.mp3
  metadata_report.txt

Musicas_Spotify_2/
  ...

Musicas_YouTube/
  ...
```

## Dependencias

O script tenta instalar automaticamente via `winget` quando necessario:

| Dependencia | Finalidade |
| --- | --- |
| Python | Executar o spotDL e o verificador de tags |
| FFmpeg | Converter audio e embutir capas |
| spotDL | Resolver links, baixar musicas e aplicar metadados |
| Mutagen | Validar e ajustar tags ID3 |
| Deno | Auxiliar downloads do YouTube em alguns casos |

## Busca online de metadados

Quando o arquivo MP3 fica sem `title`, `artist`, `album` ou capa, o `metadata_fallback.py` tenta:

1. Buscar a faixa no iTunes Search e preencher tags/capa quando encontrar uma correspondencia boa.
2. Buscar no MusicBrainz se o iTunes nao retornar um resultado confiavel.
3. Registrar tudo em `metadata_report.txt`.

Se a capa ainda nao for encontrada, o arquivo sem capa e removido e o `spotDL` faz uma segunda tentativa automatica.

## Aviso legal

Use apenas com conteudo que voce tenha direito de baixar. Baixar ou redistribuir obras protegidas sem autorizacao pode violar termos de uso de plataformas e leis de direitos autorais.
