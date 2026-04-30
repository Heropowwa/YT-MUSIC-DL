from __future__ import annotations

import os
import re
import sys
import time
import random
import base64
import subprocess
import requests
import shutil
import json
import argparse
from dataclasses import dataclass
from typing import Optional, Tuple, List
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp
from mutagen.oggopus import OggOpus
from mutagen.flac import Picture
import musicbrainzngs

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    DownloadColumn,
    TimeRemainingColumn,
)

console = Console()

# YOU NEED THIS TO MAKE METADATA REQUESTS
# GET YOUR FREE API KEY FROM: https://acoustid.org/
ACOUSTID_API_KEY = ""

musicbrainzngs.set_useragent(
    "YT_Audio_Downloader",
    "1.1",
    "https://github.com/Heropowwa/YT-MUSIC-DL"
)

REMOVE_WORDS = {
    "feat", "ft", "featuring", "with",
    "remaster", "remastered", "remastering",
    "live", "edit", "edition", "version", "mix", "mono", "stereo",
    "radio", "radioedit", "extended", "club", "dance",
    "original", "album", "single",
    "bonus", "deluxe", "expanded", "anniversary",
    "explicit", "clean",
    "demo", "rough", "instrumental", "acoustic", "karaoke",
    "soundtrack", "ost",
    "from", "motion", "picture",
    "theme", "score",
    "pt", "part", "vol", "volume",
    "disc", "cd", "track",
    "remix", "rework", "vip", "bootleg",
    "cover", "tribute",
    "intro", "outro", "interlude",
    "official", "video", "audio"
}

BRACKETS_RE = re.compile(r'[\(\[\{].*?[\)\]\}]', re.UNICODE)
CLEAN_RE = re.compile(r"[^\w\s']", re.UNICODE)

def sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-()." else "_" for c in name).strip()

def normalize_string(s: str) -> str:
    if not s:
        return ""
    s = BRACKETS_RE.sub(" ", s)
    s = s.lower()
    s = s.replace("&", " and ")
    s = CLEAN_RE.sub(" ", s)
    words = [w for w in s.split() if w not in REMOVE_WORDS]
    return " ".join(words)

def create_output_folder(base_path: str, name: str) -> str:
    safe_name = sanitize_filename(name)
    folder_path = os.path.join(base_path, safe_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def retry_request(func, max_retries=3, backoff_factor=2, *args, **kwargs):
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = backoff_factor ** attempt + random.uniform(0, 1)
            console.print(f"[yellow]Attempt {attempt} failed: {e}. Retrying in {wait:.1f}s...[/yellow]")
            time.sleep(wait)

def convert_to_opus(input_path: str, output_path: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
    command = [
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-acodec", "libopus", "-b:a", "192k",
        output_path
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed:\n{result.stderr.decode()}")
    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError("Converted Opus file missing or too small.")

def get_duration_seconds(opus_path: str) -> int:
    return int(OggOpus(opus_path).info.length)

def generate_local_fingerprint(file_path: str) -> Tuple[Optional[str], Optional[int]]:
    if not shutil.which("fpcalc"):
        console.print("[yellow]Warning: 'fpcalc' binary not found in PATH. Cannot generate fingerprint.[/yellow]")
        return None, None

    try:
        result = subprocess.run(
            ["fpcalc", "-json", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data.get("fingerprint"), data.get("duration")
    except Exception as e:
        console.print(f"[yellow]Failed to generate local fingerprint: {e}[/yellow]")
        return None, None

def get_metadata_via_picard_method(audio_path: str) -> dict:
    if not ACOUSTID_API_KEY or ACOUSTID_API_KEY == "YOUR_ACOUSTID_API_KEY_HERE":
        return {} 

    fingerprint, duration = generate_local_fingerprint(audio_path)
    if not fingerprint or not duration:
        return {}

    try:
        response = requests.get(
            "https://api.acoustid.org/v2/lookup",
            params={
                "client": ACOUSTID_API_KEY,
                "meta": "recordings",
                "duration": int(duration),
                "fingerprint": fingerprint
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "ok" or not data.get("results"):
            return {}

        best_match = data["results"][0]
        if "recordings" not in best_match or not best_match["recordings"]:
            return {}

        mbid = best_match["recordings"][0]["id"]
        
        mb_data = musicbrainzngs.get_recording_by_id(mbid, includes=["artists", "releases", "isrcs", "tags"])
        recording = mb_data.get('recording', {})
        
        tags = {
            "title": recording.get('title'),
            "artist": recording.get('artist-credit-phrase'),
            "musicbrainz_recordingid": mbid
        }

        if 'isrc-list' in recording and recording['isrc-list']:
            tags['isrc'] = recording['isrc-list'][0]
            
        if 'release-list' in recording and recording['release-list']:
            release = recording['release-list'][0]
            tags['album'] = release.get('title')
            tags['date'] = release.get('date')
            tags['musicbrainz_releaseid'] = release.get('id')
            
            if 'label-info-list' in release and release['label-info-list']:
                label_info = release['label-info-list'][0]
                tags['publisher'] = label_info.get('label', {}).get('name')
                
        return {k: v for k, v in tags.items() if v}
        
    except Exception as e:
        console.print(f"[yellow]Picard-style metadata lookup failed: {e}[/yellow]")
        return {}

def get_apple_cover(album_name, artist_name, track_name=None):
    # 1. Strip out "Unknown" defaults that pollute the iTunes search
    if album_name and "unknown" in album_name.lower():
        album_name = ""
    if artist_name and "unknown" in artist_name.lower():
        artist_name = ""
    if track_name and "unknown" in track_name.lower():
        track_name = ""

    # 2. Build a robust list of fallback queries
    queries = []

    # Try the most specific combination first (like your second script)
    full_query = " ".join(filter(None, [track_name, artist_name, album_name]))
    if full_query:
        queries.append(full_query)

    # Add progressively broader fallbacks (like your first script, but safer)
    if track_name and artist_name:
        queries.append(f"{track_name} {artist_name}")
    if artist_name and album_name:
        queries.append(f"{artist_name} {album_name}")
    if track_name:
        queries.append(track_name)
    if artist_name:
        queries.append(artist_name)

    # 3. Try each query until iTunes returns a result
    for query in queries:
        query = query.strip()
        if not query:
            continue

        params = {
            "term": query,
            "media": "music",
            "entity": "song",
            "limit": 1,
            "explicit": "Yes",
        }
        try:
            response = requests.get("https://itunes.apple.com/search", params=params, timeout=10)
            response.raise_for_status()
            results = response.json().get("results", [])

            # If we got a hit, return the high-res artwork immediately
            if results and results[0].get("artworkUrl100"):
                return results[0].get("artworkUrl100").replace("100x100bb", "1400x1400bb")
        except Exception:
            pass # Ignore connection errors and try the next fallback query

    return None

TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]")

def fetch_lyrics(artist: str, title: str, album: str, duration: int, retries: int = 2, timeout: int = 20) -> Tuple[Optional[str], Optional[str]]:
    artist_clean = normalize_string(artist)
    title_clean = normalize_string(title)
    album_clean = normalize_string(album)
    if album_clean == "unknown album":
        album_clean = ""
    params = {
        "track_name": title_clean,
        "artist_name": artist_clean,
        "album_name": album_clean,
        "duration": str(duration),
    }
    last_exception = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(
                "https://lrclib.net/api/search",
                params=params,
                timeout=timeout,
                headers={"User-Agent": "SpotifyLyricsFetcher/1.0"}
            )
            response.raise_for_status()
            data = response.json()
            if not data or not isinstance(data, list):
                return None, None
            for r in data:
                synced = r.get("syncedLyrics")
                if synced and TIMESTAMP_RE.search(synced.strip()):
                    return synced.strip(), r.get("plainLyrics")
            for r in data:
                plain = r.get("plainLyrics")
                if plain and plain.strip():
                    return None, plain.strip()
            return None, None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            last_exception = e
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            break
        except Exception as e:
            console.print(f"[yellow]Lyrics API error: {e}[/yellow]")
            return None, None
    console.print(f"[yellow]Lyrics API failed after retries: {last_exception}[/yellow]")
    return None, None

def save_lrc(lyrics: str, audio_path: str) -> bool:
    if not lyrics or not audio_path:
        return False
    try:
        base_path = os.path.splitext(audio_path)[0]
        lrc_path = f"{base_path}.lrc"
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lyrics)
        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to write lyrics:[/red] {str(e)}")
        return False

def insert_metadata(opus_path: str, info: dict, track_num: int):
    try:
        audio = OggOpus(opus_path)
    except Exception as e:
        console.print(f"[red]Could not open Opus file to tag: {e}[/red]")
        return

    # --- 1. PREPARE YOUTUBE METADATA FOR COVER SEARCH ---
    # We grab these now so MusicBrainz tags don't interfere
    yt_title = info.get("title", "")
    yt_uploader = info.get("uploader", "")
    # Clean the uploader name (e.g., removing " - Topic")
    yt_artist = yt_uploader.replace(" - Topic", "").strip()

    # --- 2. FETCH & APPLY MUSICBRAINZ TAGS (For File Organization) ---
    fp_info = get_metadata_via_picard_method(opus_path)
    for key, val in fp_info.items():
        audio[key] = [str(val)]

    # Fallback for file tags if MusicBrainz found nothing
    if 'title' not in audio:
        audio['title'] = [yt_title or "Unknown Title"]
    if 'artist' not in audio:
        audio['artist'] = [yt_artist or "Unknown Artist"]
    if 'album' not in audio:
        audio['album'] = [info.get("album") or "Unknown Album"]

    audio['tracknumber'] = [str(track_num)]

    # --- 3. FETCH COVER ART (STRICTLY USING YOUTUBE METADATA) ---
    thumb_url = None
    try:
        # We pass only the YouTube title and uploader to the search
        thumb_url = get_apple_cover("", normalize_string(yt_artist), normalize_string(yt_title))
    except Exception:
        thumb_url = None

    # --- 4. EMBED ARTWORK ---
    if thumb_url:
        try:
            response = retry_request(lambda: requests.get(thumb_url, timeout=10), max_retries=3)
            img_data = response.content
            mime = "image/png" if thumb_url.lower().endswith(".png") else "image/jpeg"

            pic = Picture()
            pic.data = img_data
            pic.type = 3
            pic.mime = mime
            pic.desc = "Cover"

            pic_data = pic.write()
            b64_data = base64.b64encode(pic_data).decode("ascii")
            audio["metadata_block_picture"] = [b64_data]
        except Exception as e:
            console.print(f"[yellow]Could not embed Apple Cover art: {e}[/yellow]")

    # --- 5. LYRICS ---
    try:
        # Use the finalized tags for lyrics search as they are usually more accurate
        artist_for_lyr = audio.get("artist", [""])[0]
        title_for_lyr = audio.get("title", [""])[0]
        album_for_lyr = audio.get("album", [""])[0]

        slyrics, _ = fetch_lyrics(artist_for_lyr, title_for_lyr, album_for_lyr, get_duration_seconds(opus_path))
        if slyrics:
            save_lrc(slyrics, opus_path)
            audio['lyrics'] = [slyrics]
    except Exception:
        pass

    audio.save()

@dataclass
class SongTask:
    url: str
    folder: str
    index: int
    playlist_total: int
    title_hint: Optional[str] = None

class WorkerDownloadHook:
    def __init__(self, progress: Progress, task_id: int):
        self.progress = progress
        self.task_id = task_id
        self._total_set = False

    def __call__(self, d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or d.get("downloaded") or 0

            if total and not self._total_set:
                try:
                    self.progress.update(self.task_id, total=total)
                except Exception:
                    pass
                self._total_set = True

            try:
                self.progress.update(self.task_id, completed=downloaded)
            except Exception:
                pass

        elif status == "finished":
            try:
                task = self.progress.tasks[self.task_id]
                total = task.total or 0
                if total:
                    self.progress.update(self.task_id, completed=total)
                else:
                    self.progress.update(self.task_id, completed=1, total=1)
            except Exception:
                pass

def build_task_list(urls: List[str], output_dir: str) -> List[SongTask]:
    tasks: List[SongTask] = []
    for url in urls:
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'skip_download': True}) as ydl:
                info = retry_request(lambda: ydl.extract_info(url, download=False), max_retries=2)
        except Exception as e:
            console.print(f"[yellow]Warning: failed to probe {url}: {e}[/yellow]")
            folder = create_output_folder(output_dir, "Single_Track")
            tasks.append(SongTask(url=url, folder=folder, index=1, playlist_total=1))
            continue

        if isinstance(info, dict) and info.get('entries'):
            playlist_title = info.get('title', f'Playlist_{int(time.time())}')
            entries = [e for e in info['entries'] if e]
            folder = create_output_folder(output_dir, playlist_title)
            console.print(f"[cyan]Playlist:[/cyan] {playlist_title} -> {len(entries)} tracks -> folder: {folder}")
            for i, entry in enumerate(entries, 1):
                video_id = entry.get('id')
                if not video_id:
                    console.print(f"[yellow]Skipping entry {i}: Missing video ID[/yellow]")
                    continue
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                title_hint = entry.get('title')
                tasks.append(SongTask(url=video_url, folder=folder, index=i, playlist_total=len(entries), title_hint=title_hint))
        else:
            folder = create_output_folder(output_dir, "Single_Track")
            hint = None
            if isinstance(info, dict):
                hint = info.get('title')
            tasks.append(SongTask(url=url, folder=folder, index=1, playlist_total=1, title_hint=hint))
    return tasks

def worker_loop(worker_id: int, job_queue: Queue, progress: Progress, worker_task_id: int, overall_task_id: int):
    while True:
        try:
            song: SongTask = job_queue.get_nowait()
        except Empty:
            try:
                progress.update(worker_task_id, description=f"[grey58]Worker {worker_id} idle[/grey58]", completed=0, total=1)
            except Exception:
                pass
            return

        desc_title = song.title_hint or song.url
        short_desc = f"W{worker_id} {song.index}/{song.playlist_total} {desc_title}"
        try:
            progress.update(worker_task_id, description=short_desc, completed=0, total=1)
        except Exception:
            pass

        safe_prefix = sanitize_filename(f"{song.index:02d} - ")
        outtmpl = os.path.join(song.folder, f"{safe_prefix}%(title)s.%(ext)s")

        hook = WorkerDownloadHook(progress, worker_task_id)
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(song.folder, f"{safe_prefix}%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "opus",
            }],
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "progress_hooks": [hook],
        }

        success = False
        for attempt in range(1, 4):
            try:
                def _dl():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(song.url, download=True)
                        if info is None:
                            raise RuntimeError("yt_dlp returned None.")
                        return info, ydl
                
                info, ydl_instance = retry_request(_dl, max_retries=2)
                
                final_path = ydl_instance.prepare_filename(info)
                full_path = os.path.splitext(final_path)[0] + ".opus"

                if not os.path.isfile(full_path) or os.path.getsize(full_path) < 1024:
                    raise RuntimeError("Downloaded file missing or too small.")

                try:
                    progress.update(worker_task_id, description=f"{short_desc} • tagging (MusicBrainz)")
                except Exception:
                    pass
                
                try:
                    insert_metadata(full_path, info, song.index)
                except Exception:
                    pass

                success = True
                break

            except Exception as e:
                console.print(f"[red]Worker {worker_id} attempt {attempt} failed for {song.url}: {e}[/red]")
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    try:
                        progress.update(worker_task_id, completed=0, total=1)
                    except Exception:
                        pass
                    continue
                else:
                    console.print(f"[bold red]Worker {worker_id} giving up on {song.url}[/bold red]")
            finally:
                pass
        try:
            progress.update(overall_task_id, advance=1)
        except Exception:
            pass

        try:
            progress.update(worker_task_id, description=f"[grey58]Worker {worker_id} idle[/grey58]", completed=0, total=1)
        except Exception:
            pass

        job_queue.task_done()

def main():
    default_workers = min(4, (os.cpu_count() or 2))

    parser = argparse.ArgumentParser(
        description="A professional YouTube audio downloader with metadata and lyrics support.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "urls",
        nargs="*",
        help="YouTube URLs to download (video or playlist)"
    )
    parser.add_argument(
        "-b", "--batch-file",
        type=str,
        help="Path to a text file containing a list of YouTube URLs (one per line)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=os.getcwd(),
        help="Directory to save the downloaded audio files"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=default_workers,
        help="Number of concurrent download workers"
    )

    args = parser.parse_args()

    console.print(Panel.fit("[bold cyan]YouTube Downloader[/bold cyan]", border_style="cyan"))

    urls: List[str] = list(args.urls)

    if args.batch_file:
        if os.path.isfile(args.batch_file):
            with open(args.batch_file, "r", encoding="utf-8") as f:
                urls.extend([line.strip() for line in f if line.strip() and not line.startswith("#")])
        else:
            console.print(f"[yellow]Warning: Batch file '{args.batch_file}' not found.[/yellow]")

    if not urls:
        parser.print_help()
        console.print("\n[red]Error: No URLs provided. Please provide URLs directly or via a batch file.[/red]")
        sys.exit(1)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    MAX_WORKERS = max(1, args.workers)

    console.print(f"[green]Preparing tasks and expanding playlists...[/green]")
    tasks = build_task_list(urls, output_dir)
    total_tracks = len(tasks)
    console.print(f"[green]Total tracks to process:[/green] {total_tracks}")

    job_queue: Queue = Queue()
    for t in tasks:
        job_queue.put(t)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    try:
        with progress:
            overall_task_id = progress.add_task("[bold magenta]Overall[/bold magenta]", total=total_tracks)
            worker_task_ids = []
            for wid in range(1, MAX_WORKERS + 1):
                tid = progress.add_task(f"[grey58]Worker {wid} idle[/grey58]", total=1)
                worker_task_ids.append(tid)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for i, tid in enumerate(worker_task_ids, start=1):
                    futures.append(executor.submit(worker_loop, i, job_queue, progress, tid, overall_task_id))

                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as e:
                        console.print(f"[red]Worker thread exception: {e}[/red]")

            job_queue.join()

    except KeyboardInterrupt:
        console.print("\n[red]Cancelled by user[/red]")
        sys.exit(1)

    console.print(Panel.fit("[bold green]All downloads completed (or attempted).[/bold green]", border_style="green"))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Cancelled by user[/red]")
        sys.exit(1)
