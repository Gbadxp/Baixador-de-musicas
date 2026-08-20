import glob
import json
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp3 import MP3


USER_AGENT = "BaixarMusicasMetadados/1.0 (local script)"
REPORT_FILE = "metadata_report.txt"


def http_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def http_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read(), response.headers.get("Content-Type", "")


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def first(values):
    if not values:
        return ""
    return clean(values[0])


def score_match(title, artist, candidate_title, candidate_artist):
    wanted = f"{title} {artist}".lower().strip()
    candidate = f"{candidate_title} {candidate_artist}".lower().strip()
    if not wanted or not candidate:
        return 0.0
    return SequenceMatcher(None, wanted, candidate).ratio()


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


def guess_mime(data, content_type, url):
    content_type = (content_type or "").split(";")[0].strip()
    if content_type.startswith("image/"):
        return content_type
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    guessed, _ = mimetypes.guess_type(url)
    return guessed or "image/jpeg"


def embed_cover(path, artwork_url):
    if not artwork_url:
        return False
    try:
        data, content_type = http_bytes(artwork_url)
        if not data:
            return False
        mime = guess_mime(data, content_type, artwork_url)
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        tags.save(path, v2_version=3)
        return True
    except Exception:
        return False


def best_itunes_match(title, artist):
    term = " ".join(part for part in [title, artist] if part)
    if not term:
        return None

    params = urllib.parse.urlencode(
        {
            "term": term,
            "entity": "song",
            "limit": "8",
            "country": "BR",
        }
    )
    url = f"https://itunes.apple.com/search?{params}"
    data = http_json(url)
    results = data.get("results", [])
    if not results:
        return None

    ranked = sorted(
        results,
        key=lambda item: score_match(
            title,
            artist,
            item.get("trackName", ""),
            item.get("artistName", ""),
        ),
        reverse=True,
    )
    best = ranked[0]
    if score_match(title, artist, best.get("trackName", ""), best.get("artistName", "")) < 0.50:
        return None

    artwork = best.get("artworkUrl100", "")
    artwork = artwork.replace("100x100", "600x600")
    return {
        "source": "iTunes Search",
        "title": best.get("trackName", ""),
        "artist": best.get("artistName", ""),
        "album": best.get("collectionName", ""),
        "albumartist": best.get("artistName", ""),
        "date": best.get("releaseDate", "")[:10],
        "genre": best.get("primaryGenreName", ""),
        "tracknumber": str(best.get("trackNumber", "") or ""),
        "discnumber": str(best.get("discNumber", "") or ""),
        "artwork": artwork,
    }


def best_musicbrainz_match(title, artist):
    term = " ".join(part for part in [title, artist] if part)
    if not term:
        return None

    query = urllib.parse.quote(term)
    url = (
        "https://musicbrainz.org/ws/2/recording"
        f"?query={query}&fmt=json&limit=5&inc=artist-credits+releases"
    )
    data = http_json(url)
    recordings = data.get("recordings", [])
    if not recordings:
        return None

    ranked = sorted(
        recordings,
        key=lambda item: score_match(
            title,
            artist,
            item.get("title", ""),
            item.get("artist-credit-phrase", ""),
        ),
        reverse=True,
    )
    best = ranked[0]
    if score_match(title, artist, best.get("title", ""), best.get("artist-credit-phrase", "")) < 0.45:
        return None

    releases = best.get("releases", []) or []
    release = releases[0] if releases else {}
    return {
        "source": "MusicBrainz",
        "title": best.get("title", ""),
        "artist": best.get("artist-credit-phrase", ""),
        "album": release.get("title", ""),
        "albumartist": best.get("artist-credit-phrase", ""),
        "date": release.get("date", "") or best.get("first-release-date", ""),
        "genre": "",
        "tracknumber": "",
        "discnumber": "",
        "artwork": "",
    }


def find_metadata(title, artist):
    errors = []
    for finder in (best_itunes_match, best_musicbrainz_match):
        try:
            result = finder(title, artist)
            if result:
                return result, errors
        except Exception as exc:
            errors.append(f"{finder.__name__}: {exc}")
        time.sleep(1)
    return None, errors


def normalize_artist(value):
    artist = clean(value).replace(";", ",")
    return artist.split(",")[0].split("/")[0].strip()


def fill_missing_tags(path, metadata):
    easy = get_easy_tags(path)
    changed = False

    mapping = {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "albumartist": "albumartist",
        "date": "date",
        "genre": "genre",
        "tracknumber": "tracknumber",
        "discnumber": "discnumber",
    }

    for tag_name, meta_name in mapping.items():
        value = clean(metadata.get(meta_name, ""))
        if value and not first(easy.get(tag_name, [])):
            easy[tag_name] = value
            changed = True

    current_artist = first(easy.get("artist", []))
    normalized = normalize_artist(current_artist)
    if normalized and current_artist != normalized:
        easy["artist"] = normalized
        changed = True
    if normalized and "albumartist" not in easy:
        easy["albumartist"] = normalized
        changed = True

    if changed:
        easy.save(v2_version=3)
    return changed


def missing_required_tags(path):
    try:
        easy = get_easy_tags(path)
    except Exception:
        return ["title", "artist", "album"]

    missing = []
    for tag in ("title", "artist", "album"):
        if not first(easy.get(tag, [])):
            missing.append(tag)
    return missing


def process_file(path):
    report = []
    easy = get_easy_tags(path)
    title = first(easy.get("title", []))
    artist = first(easy.get("artist", []))

    parsed_title, parsed_artist = parse_from_filename(path)
    title = title or parsed_title
    artist = artist or parsed_artist

    cover_before = has_cover(path)
    missing_before = missing_required_tags(path)
    needs_search = bool(missing_before) or not cover_before

    fixed_tags = False
    fixed_cover = False
    source = ""

    if needs_search:
        metadata, errors = find_metadata(title, artist)
        report.extend(errors)
        if metadata:
            source = metadata.get("source", "")
            fixed_tags = fill_missing_tags(path, metadata)
            if not cover_before and metadata.get("artwork"):
                fixed_cover = embed_cover(path, metadata["artwork"])
        else:
            report.append(f"SEM RESULTADO ONLINE: {path}")
    else:
        artist_value = first(easy.get("artist", []))
        normalized = normalize_artist(artist_value)
        if normalized and artist_value != normalized:
            easy["artist"] = normalized
            easy["albumartist"] = normalized
            easy.save(v2_version=3)
            fixed_tags = True

    cover_after = has_cover(path)
    missing_after = missing_required_tags(path)
    removed_for_retry = False
    if not cover_after:
        try:
            os.remove(path)
            removed_for_retry = True
        except OSError:
            pass

    return {
        "path": path,
        "source": source,
        "fixed_tags": fixed_tags,
        "fixed_cover": fixed_cover,
        "missing_tags": missing_after,
        "has_cover": cover_after,
        "removed_for_retry": removed_for_retry,
        "report": report,
    }


def main():
    files = sorted(glob.glob("**/*.mp3", recursive=True))
    results = []
    for path in files:
        try:
            results.append(process_file(path))
        except Exception as exc:
            results.append(
                {
                    "path": path,
                    "source": "",
                    "fixed_tags": False,
                    "fixed_cover": False,
                    "missing_tags": ["erro"],
                    "has_cover": False,
                    "removed_for_retry": False,
                    "report": [f"ERRO {path}: {exc}"],
                }
            )

    removed = [item for item in results if item["removed_for_retry"]]
    incomplete = [item for item in results if item["missing_tags"]]
    fixed_tags = [item for item in results if item["fixed_tags"]]
    fixed_covers = [item for item in results if item["fixed_cover"]]

    with open(REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"Arquivos MP3 verificados: {len(files)}\n")
        fh.write(f"Tags preenchidas pela internet: {len(fixed_tags)}\n")
        fh.write(f"Capas preenchidas pela internet: {len(fixed_covers)}\n")
        fh.write(f"Arquivos removidos para nova tentativa: {len(removed)}\n")
        fh.write(f"Arquivos ainda com tags incompletas: {len(incomplete)}\n\n")

        for item in results:
            if item["source"] or item["fixed_tags"] or item["fixed_cover"]:
                fh.write(f"OK ONLINE: {item['path']} ({item['source'] or 'tags locais'})\n")
            if item["missing_tags"]:
                fh.write(
                    f"METADADOS INCOMPLETOS: {item['path']} "
                    f"({', '.join(item['missing_tags'])})\n"
                )
            if item["removed_for_retry"]:
                fh.write(f"SEM CAPA: {item['path']}\n")
            for line in item["report"]:
                fh.write(line + "\n")

    print(f"MP3 verificados: {len(files)}")
    print(f"Tags preenchidas pela internet: {len(fixed_tags)}")
    print(f"Capas preenchidas pela internet: {len(fixed_covers)}")
    if removed:
        print(f"Sem capa, removidos para tentar de novo: {len(removed)}")
        return 1
    if incomplete:
        print(f"Ainda com metadados incompletos: {len(incomplete)}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
