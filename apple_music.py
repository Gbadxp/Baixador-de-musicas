"""Le as musicas de um link do Apple Music (so metadados, pela API publica da Apple).

O audio nao vem do Apple Music, que e protegido por DRM. Os metadados (titulo,
artista, album, capa, duracao) vao para um arquivo .spotdl, e o spotDL busca o
audio no YouTube, como nos links do Spotify.
"""

import dataclasses
import json
import re
import urllib.parse
import urllib.request

LINK_RE = re.compile(
    r"music\.apple\.com/(?P<country>[a-z]{2})/(?P<kind>album|song|playlist)/(?:[^/?#]+/)?(?P<id>[^/?#]+)"
)
SONG_ID_RE = re.compile(r"music\.apple\.com/[a-z]{2}/song/(?:[^/?#]+/)?(\d+)")
LOOKUP_BATCH = 100


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def lookup(ids, country, entity=None):
    """API publica do iTunes (Lookup), que aceita varios IDs por chamada."""
    results = []
    for start in range(0, len(ids), LOOKUP_BATCH):
        params = {"id": ",".join(ids[start:start + LOOKUP_BATCH]), "country": country}
        if entity:
            params["entity"] = entity
        data = json.loads(fetch("https://itunes.apple.com/lookup?" + urllib.parse.urlencode(params)))
        results += data.get("results", [])
    return [item for item in results if item.get("wrapperType") == "track" and item.get("kind") == "song"]


def playlist_song_ids(url):
    """Nome, IDs das musicas e total informado pela pagina publica da playlist."""
    html = fetch(url)
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        data = json.loads(block)
        if data.get("@type") == "MusicPlaylist":
            ids = []
            for track in data.get("track") or []:
                match = SONG_ID_RE.search(track.get("url", ""))
                if match:
                    ids.append(match.group(1))
            return data.get("name", ""), ids, data.get("numTracks") or len(ids)
    raise ValueError("Não consegui ler a playlist do Apple Music. Ela precisa ser pública.")


def read_link(url):
    """Devolve (nome, faixas do iTunes Lookup, avisos) de um link de musica, album ou playlist."""
    match = LINK_RE.search(url)
    if not match:
        raise ValueError("Link do Apple Music não suportado. Use um link de música, álbum ou playlist.")
    country, kind, item_id = match.group("country", "kind", "id")
    # Musica aberta dentro de um album: .../album/nome/123?i=456
    song_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("i", [None])[0]
    warnings = []

    if kind == "playlist":
        name, ids, total = playlist_song_ids(url)
        by_id = {str(song["trackId"]): song for song in lookup(ids, country)}
        songs = [by_id[track_id] for track_id in ids if track_id in by_id]
        if total > len(ids):
            warnings.append(f"A página do Apple Music mostrou só {len(ids)} das {total} músicas da playlist.")
        if len(songs) < len(ids):
            warnings.append(f"{len(ids) - len(songs)} música(s) não estão disponíveis na loja {country.upper()}.")
    elif kind == "song" or song_id:
        songs = lookup([song_id or item_id], country)
        name = songs[0]["trackName"] if songs else ""
    else:
        songs = sorted(
            lookup([item_id], country, entity="song"),
            key=lambda song: (song.get("discNumber") or 0, song.get("trackNumber") or 0),
        )
        name = songs[0].get("collectionName", "") if songs else ""

    if not songs:
        raise ValueError("Nenhuma música encontrada nesse link do Apple Music.")
    return name, songs, warnings


def write_spotdl_file(songs, list_name, list_url, path):
    """Grava as faixas no formato .spotdl que o spotDL aceita como entrada.

    Com todos os campos preenchidos o spotDL nao consulta o Spotify: so busca o
    audio no YouTube (usando a duracao para achar o video certo) e grava as tags."""
    from spotdl.types.song import Song

    entries = []
    for position, song in enumerate(songs, 1):
        artwork = song.get("artworkUrl100") or ""
        values = {
            "name": song["trackName"],
            "artists": [song["artistName"]],
            "artist": song["artistName"],
            "genres": [song["primaryGenreName"]] if song.get("primaryGenreName") else [],
            "disc_number": song.get("discNumber") or 1,
            "disc_count": song.get("discCount") or 1,
            "album_name": song.get("collectionName") or song["trackName"],
            "album_artist": song.get("collectionArtistName") or song["artistName"],
            "duration": round((song.get("trackTimeMillis") or 0) / 1000),
            "year": int(song["releaseDate"][:4]) if song.get("releaseDate") else 0,
            "date": (song.get("releaseDate") or "")[:10],
            "track_number": song.get("trackNumber") or 1,
            "tracks_count": song.get("trackCount") or 1,
            "song_id": str(song["trackId"]),
            "explicit": song.get("trackExplicitness") == "explicit",
            "publisher": "",
            "url": song.get("trackViewUrl") or list_url,
            # A Apple nao informa o ISRC, e o spotDL quebra ao gravar MP3 com None.
            "isrc": "",
            "cover_url": artwork.replace("100x100bb", "1000x1000bb") or None,
            "album_id": str(song.get("collectionId") or song["trackId"]),
            "artist_id": str(song.get("artistId") or ""),
            "list_name": list_name,
            "list_url": list_url,
            "list_position": position,
            "list_length": len(songs),
        }
        # Usa os campos da versao instalada do spotDL; os que a Apple nao tem ficam vazios.
        entries.append({field.name: values.get(field.name) for field in dataclasses.fields(Song)})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False)
