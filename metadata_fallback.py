"""Valida e completa os metadados (tags ID3 e capa) dos MP3 baixados.

Usado pela janela (app.py), mas tambem funciona sozinho no terminal:

    python metadata_fallback.py [pasta]          # 1a passada
    python metadata_fallback.py [pasta] --final  # depois da nova tentativa

Na 1a passada, musicas que continuam sem capa sao movidas para a subpasta
_sem_capa_aguardando, para que o spotDL as baixe de novo. Na passada final,
nada e removido: se a musica nao foi baixada de novo, o arquivo antigo volta.

Codigos de saida: 0 = tudo OK, 1 = musicas separadas para nova tentativa,
2 = ainda ha musicas sem capa ou com tags incompletas.
"""

import argparse
import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp3 import MP3


USER_AGENT = "BaixadorDeMusicas/2.0 ( https://github.com/Gbadxp/Baixador-de-musicas )"
REPORT_FILE = "metadata_report.txt"
RETRY_DIR = "_sem_capa_aguardando"
REQUIRED_TAGS = ("title", "artist", "album")
MIN_SCORE = 0.75

# Artistas que tem "/" no proprio nome e nao podem ser divididos.
NAMES_WITH_SLASH = ("ac/dc", "au/ra")

# Intervalo minimo entre chamadas: iTunes aceita ~20 por minuto, MusicBrainz 1 por segundo.
API_INTERVAL = {"itunes": 3.1, "musicbrainz": 1.1}
_last_call = {}


def throttle(service):
    wait = API_INTERVAL[service] - (time.monotonic() - _last_call.get(service, -1e9))
    if wait > 0:
        time.sleep(wait)
    _last_call[service] = time.monotonic()


def http_json(url, retries=1):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        # 503 = limite de requisicoes temporario (comum no MusicBrainz).
        if exc.code == 503 and retries > 0:
            time.sleep(3)
            return http_json(url, retries - 1)
        raise


def http_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(), response.headers.get("Content-Type", "")


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def first(values):
    if not values:
        return ""
    return clean(values[0])


# ----------------------------------------------------------------------------
# Comparacao de titulos e artistas
# ----------------------------------------------------------------------------

def strip_extras(text):
    """Remove "(Remastered)", "[Ao Vivo]", "feat. X" e " - Remastered 2011"."""
    text = clean(text)
    stripped = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)
    stripped = re.sub(r"\s(?:feat\.?|ft\.?|featuring)\s.*$", " ", stripped, flags=re.I)
    stripped = re.sub(r"\s-\s.*$", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or text


def simplify(text):
    """Deixa o texto comparavel: sem acentos, extras, maiusculas e pontuacao."""
    text = unicodedata.normalize("NFKD", strip_extras(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def similarity(a, b):
    a, b = simplify(a), simplify(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def main_artist(name):
    """Primeiro artista de "A, B", "A & B", "A feat. B"... usado so para comparar e buscar."""
    parts = re.split(
        r"\s*(?:,|/|;|&|\s(?:feat\.?|ft\.?|x|and|e)\s)\s*",
        clean(name),
        maxsplit=1,
        flags=re.I,
    )
    return parts[0].strip()


def artist_similarity(wanted, candidate):
    return max(
        similarity(wanted, candidate),
        similarity(main_artist(wanted), main_artist(candidate)),
    )


def score_match(title, artist, candidate_title, candidate_artist):
    """Nota de 0 a 1. Retorna 0 quando claramente nao e a mesma faixa."""
    title_score = similarity(title, candidate_title)
    if not artist:
        # Sem artista para conferir, so aceita titulo praticamente identico.
        return title_score if title_score >= 0.9 else 0.0
    artist_score = artist_similarity(artist, candidate_artist)
    if title_score < 0.7 or artist_score < 0.5:
        return 0.0
    return 0.65 * title_score + 0.35 * artist_score


def best_scored(candidates, title, artist, get_title, get_artist):
    scored = [
        (score_match(title, artist, get_title(item), get_artist(item)), item)
        for item in candidates
    ]
    score, best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
    if best is None or score < MIN_SCORE:
        return None
    return best


# ----------------------------------------------------------------------------
# Leitura e escrita das tags
# ----------------------------------------------------------------------------

def parse_from_filename(path):
    stem = Path(path).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return clean(title), clean(artist)
    return clean(stem), ""


def get_easy_tags(path):
    try:
        return EasyID3(path)
    except ID3NoHeaderError:
        audio = MP3(path, ID3=ID3)
        audio.add_tags()
        audio.save(v2_version=3)
        return EasyID3(path)


def has_cover(path):
    try:
        tags = ID3(path)
    except Exception:
        return False
    return any(isinstance(tag, APIC) for tag in tags.values())


def image_mime(data, content_type):
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type.startswith("image/"):
        return content_type
    return ""


def embed_cover(path, artwork_urls):
    """Embute a primeira imagem valida da lista. Retorna True se conseguiu."""
    for url in artwork_urls:
        try:
            data, content_type = http_bytes(url)
        except Exception:
            continue
        mime = image_mime(data, content_type)
        if not data or not mime:
            continue
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        tags.save(path, v2_version=3)
        return True
    return False


def primary_artist(artists, albumartist=""):
    """Escolhe o artista principal sem quebrar nomes como "AC/DC" ou "Tyler, The Creator"."""
    artists = [clean(value) for value in artists if clean(value)]
    if not artists:
        return ""
    if len(artists) > 1:
        # Tag com varios valores (ID3v2.4): o primeiro e o principal.
        return artists[0]

    artist = artists[0]
    lower = artist.lower()
    albumartist = clean(albumartist)
    if albumartist and lower.startswith(albumartist.lower()):
        return artist[: len(albumartist)]

    for name in NAMES_WITH_SLASH:
        if lower == name or lower.startswith(name + "/"):
            return artist[: len(name)]

    # O spotDL junta varios artistas com "/" (ID3v2.3). Partes muito curtas
    # indicam que a barra faz parte do nome, entao o nome fica intacto.
    if "/" in artist:
        parts = [part.strip() for part in artist.split("/")]
        if all(len(part) > 2 for part in parts):
            return parts[0]
    if ";" in artist:
        return artist.split(";")[0].strip()
    # Virgula nao e separador: "Tyler, The Creator" e "Earth, Wind & Fire" sao um artista so.
    return artist


def normalize_artist_tags(easy):
    """Deixa so o artista principal e preenche albumartist se faltar (Apple Music/iPhone)."""
    changed = False
    artists = easy.get("artist", [])
    albumartist = first(easy.get("albumartist", []))
    primary = primary_artist(artists, albumartist)
    if primary and [clean(value) for value in artists] != [primary]:
        easy["artist"] = primary
        changed = True
    if primary and not albumartist:
        easy["albumartist"] = primary
        changed = True
    return changed


def fill_missing_tags(easy, metadata):
    changed = False
    for tag in ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber", "discnumber"):
        value = clean(metadata.get(tag, ""))
        if value and not first(easy.get(tag, [])):
            easy[tag] = value
            changed = True
    return changed


def missing_required_tags(easy):
    return [tag for tag in REQUIRED_TAGS if not first(easy.get(tag, []))]


# ----------------------------------------------------------------------------
# Busca online
# ----------------------------------------------------------------------------

def best_itunes_match(title, artist):
    term = " ".join(part for part in (strip_extras(title), main_artist(artist)) if part)
    if not term:
        return None

    throttle("itunes")
    params = urllib.parse.urlencode(
        {
            "term": term,
            "entity": "song",
            "limit": "10",
            "country": "BR",
        }
    )
    data = http_json(f"https://itunes.apple.com/search?{params}")
    best = best_scored(
        data.get("results", []),
        title,
        artist,
        lambda item: item.get("trackName", ""),
        lambda item: item.get("artistName", ""),
    )
    if not best:
        return None

    artwork = clean(best.get("artworkUrl100"))
    return {
        "source": "iTunes Search",
        "title": best.get("trackName", ""),
        "artist": best.get("artistName", ""),
        "album": best.get("collectionName", ""),
        "albumartist": best.get("collectionArtistName") or best.get("artistName", ""),
        "date": clean(best.get("releaseDate"))[:10],
        "genre": best.get("primaryGenreName", ""),
        "tracknumber": str(best.get("trackNumber", "") or ""),
        "discnumber": str(best.get("discNumber", "") or ""),
        "artwork": [artwork.replace("100x100", "600x600"), artwork] if artwork else [],
    }


def lucene_phrase(text):
    return '"' + re.sub(r'([\\"])', r"\\\1", text) + '"'


def credit_name(credits):
    """Monta "Artista A feat. Artista B" a partir do campo artist-credit da API."""
    parts = []
    for credit in credits or []:
        name = credit.get("name") or (credit.get("artist") or {}).get("name", "")
        parts.append(f"{name}{credit.get('joinphrase', '')}")
    return "".join(parts).strip()


def best_musicbrainz_match(title, artist):
    search_title = strip_extras(title)
    if not search_title:
        return None

    query = f"recording:{lucene_phrase(search_title)}"
    if artist:
        query += f" AND artist:{lucene_phrase(main_artist(artist))}"

    throttle("musicbrainz")
    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": "10"})
    data = http_json(f"https://musicbrainz.org/ws/2/recording?{params}")
    best = best_scored(
        data.get("recordings", []),
        title,
        artist,
        lambda item: item.get("title", ""),
        lambda item: credit_name(item.get("artist-credit")),
    )
    if not best:
        return None

    releases = best.get("releases") or []
    official = [item for item in releases if item.get("status") == "Official"] or releases
    # O lancamento mais antigo costuma ser o album original (nao coletanea/ao vivo).
    official = sorted(official, key=lambda item: item.get("date") or "9999")
    release = official[0] if official else {}
    media = release.get("media") or [{}]
    tracks = media[0].get("track") or [{}]
    artist_name = credit_name(best.get("artist-credit"))
    return {
        "source": "MusicBrainz",
        "title": best.get("title", ""),
        "artist": artist_name,
        "album": release.get("title", ""),
        "albumartist": credit_name(release.get("artist-credit")) or artist_name,
        "date": release.get("date", "") or best.get("first-release-date", ""),
        "genre": "",
        "tracknumber": clean(tracks[0].get("number")),
        "discnumber": clean(media[0].get("position")),
        # MusicBrainz nao tem imagens; as capas ficam no Cover Art Archive.
        "artwork": [
            f"https://coverartarchive.org/release/{item['id']}/front-500"
            for item in official[:3]
            if item.get("id")
        ],
    }


def find_metadata(title, artist):
    errors = []
    for finder in (best_itunes_match, best_musicbrainz_match):
        try:
            result = finder(title, artist)
        except Exception as exc:
            errors.append(f"{finder.__name__}: {exc}")
            continue
        if result:
            return result, errors
    return None, errors


# ----------------------------------------------------------------------------
# Processamento da pasta
# ----------------------------------------------------------------------------

def process_file(path, folder, can_set_aside):
    report = []
    name = str(path.relative_to(folder))
    easy = get_easy_tags(path)
    file_title, file_artist = parse_from_filename(path)
    title = first(easy.get("title", [])) or file_title
    artist = first(easy.get("artist", [])) or file_artist

    cover_before = has_cover(path)
    needs_search = bool(missing_required_tags(easy)) or not cover_before
    metadata = None
    fixed_tags = False
    fixed_cover = False

    if needs_search:
        metadata, errors = find_metadata(title, artist)
        report.extend(errors)
        if metadata:
            fixed_tags = fill_missing_tags(easy, metadata)
        else:
            report.append(f"SEM RESULTADO ONLINE: {name}")

    if normalize_artist_tags(easy):
        fixed_tags = True
    if fixed_tags:
        easy.save(v2_version=3)

    # A capa e gravada depois das tags, senao o easy.save() acima a apagaria.
    if metadata and not cover_before:
        fixed_cover = embed_cover(path, metadata.get("artwork", []))

    cover_after = has_cover(path)
    missing_after = missing_required_tags(get_easy_tags(path))

    set_aside = False
    if not cover_after and can_set_aside:
        target = folder / RETRY_DIR / path.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        set_aside = True

    return {
        "name": name,
        "source": metadata.get("source", "") if metadata else "",
        "fixed_tags": fixed_tags,
        "fixed_cover": fixed_cover,
        "missing_tags": missing_after,
        "has_cover": cover_after,
        "set_aside": set_aside,
        "report": report,
    }


def restore_set_aside(folder):
    """Depois da nova tentativa, descarta a copia antiga se a musica foi
    baixada de novo; senao devolve o arquivo antigo. Nunca perde musica."""
    retry_dir = folder / RETRY_DIR
    replaced = restored = 0
    if not retry_dir.is_dir():
        return replaced, restored

    for old in sorted(retry_dir.rglob("*.mp3")):
        target = folder / old.relative_to(retry_dir)
        if target.exists():
            old.unlink()
            replaced += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(target))
            restored += 1

    for directory in sorted(retry_dir.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if not any(retry_dir.iterdir()):
        retry_dir.rmdir()
    return replaced, restored


def list_mp3(folder):
    return sorted(
        path
        for path in folder.rglob("*.mp3")
        if RETRY_DIR not in path.relative_to(folder).parts
    )


def write_report(folder, summary, results):
    with open(folder / REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"Arquivos MP3 verificados: {summary['checked']}\n")
        fh.write(f"Tags preenchidas/ajustadas: {summary['fixed_tags']}\n")
        fh.write(f"Capas encontradas na internet: {summary['fixed_covers']}\n")
        fh.write(f"Separados para nova tentativa: {summary['set_aside']}\n")
        fh.write(f"Sem capa (mantidos): {summary['without_cover']}\n")
        fh.write(f"Com tags incompletas: {summary['incomplete']}\n\n")

        for item in results:
            if item["source"] or item["fixed_cover"]:
                fh.write(f"OK ONLINE: {item['name']} ({item['source'] or 'tags locais'})\n")
            if item["missing_tags"]:
                fh.write(f"METADADOS INCOMPLETOS: {item['name']} ({', '.join(item['missing_tags'])})\n")
            if item["set_aside"]:
                fh.write(f"SEM CAPA, NOVA TENTATIVA: {item['name']}\n")
            elif not item["has_cover"]:
                fh.write(f"SEM CAPA (mantido): {item['name']}\n")
            for line in item["report"]:
                fh.write(line + "\n")


def run(folder=".", final=False, log=print, stop=lambda: False):
    """Verifica todos os MP3 da pasta e devolve um resumo com o codigo de saida.

    stop() e consultado entre um arquivo e outro para permitir cancelar."""
    folder = Path(folder).resolve()
    if final:
        replaced, restored = restore_set_aside(folder)
        if replaced:
            log(f"{replaced} música(s) foram baixadas de novo.")
        if restored:
            log(f"{restored} música(s) continuam sem capa, mas foram mantidas.")

    files = list_mp3(folder)
    results = []
    for index, path in enumerate(files, 1):
        if stop():
            break
        log(f"Verificando tags ({index}/{len(files)}): {path.name}")
        try:
            results.append(process_file(path, folder, can_set_aside=not final))
        except Exception as exc:
            results.append(
                {
                    "name": str(path.relative_to(folder)),
                    "source": "",
                    "fixed_tags": False,
                    "fixed_cover": False,
                    "missing_tags": ["erro"],
                    "has_cover": path.exists() and has_cover(path),
                    "set_aside": False,
                    "report": [f"ERRO {path.name}: {exc}"],
                }
            )

    summary = {
        "checked": len(files),
        "fixed_tags": sum(1 for item in results if item["fixed_tags"]),
        "fixed_covers": sum(1 for item in results if item["fixed_cover"]),
        "set_aside": sum(1 for item in results if item["set_aside"]),
        "without_cover": sum(1 for item in results if not item["has_cover"] and not item["set_aside"]),
        "incomplete": sum(1 for item in results if item["missing_tags"]),
    }
    if summary["set_aside"]:
        summary["code"] = 1
    elif summary["without_cover"] or summary["incomplete"]:
        summary["code"] = 2
    else:
        summary["code"] = 0

    write_report(folder, summary, results)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Valida e completa tags/capas dos MP3 baixados.")
    parser.add_argument("pasta", nargs="?", default=".", help="pasta com os MP3 (padrão: pasta atual)")
    parser.add_argument("--final", action="store_true", help="passada final: não separa nem remove nada")
    args = parser.parse_args()

    summary = run(args.pasta, final=args.final)
    print(f"MP3 verificados: {summary['checked']}")
    print(f"Tags preenchidas/ajustadas: {summary['fixed_tags']}")
    print(f"Capas encontradas na internet: {summary['fixed_covers']}")
    if summary["set_aside"]:
        print(f"Sem capa, separados para nova tentativa: {summary['set_aside']}")
    if summary["without_cover"]:
        print(f"Sem capa (mantidos): {summary['without_cover']}")
    if summary["incomplete"]:
        print(f"Com tags incompletas: {summary['incomplete']}")
    return summary["code"]


if __name__ == "__main__":
    sys.exit(main())
