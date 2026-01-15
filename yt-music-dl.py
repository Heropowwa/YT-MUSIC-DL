from __future__ import annotations

import os
import re
import sys
import time
import random
import subprocess
import requests
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple, List
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, error

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

def convert_to_mp3(input_path: str, output_path: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
    command = [
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "320k",
        output_path
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed:\n{result.stderr.decode()}")
    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError("Converted MP3 missing or too small.")

def get_duration_seconds(mp3_path: str) -> int:
    return int(MP3(mp3_path).info.length)

def get_apple_cover(album_name, artist_name, track_name=None):
    query_parts = []
    if track_name:
        query_parts.append(track_name)
    if artist_name:
        query_parts.append(artist_name)
    if album_name:
        query_parts.append(album_name)
    query = " ".join(query_parts).strip()
    params = {
        "term": query,
        "media": "music",
        "entity": "song",
        "limit": 1,
        "explicit": "Yes",
    }
    response = requests.get("https://itunes.apple.com/search", params=params, timeout=10)
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return None
    artwork = results[0].get("artworkUrl100")
    if not artwork:
        return None
    return artwork.replace("100x100bb", "1400x1400bb")

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

def insert_metadata(mp3_path: str, info: dict, track_num: int):
    try:
        audio = ID3(mp3_path)
    except error.ID3NoHeaderError:
        audio = ID3()
    title = info.get("title", "Unknown Title")
    raw_artist = info.get("artist") or info.get("uploader") or "Unknown Artist"
    artist = re.split(r",|&| feat\.?| featuring ", raw_artist, flags=re.IGNORECASE)[0].strip()
    album = info.get("album") or "Unknown Album"

    audio["TIT2"] = TIT2(encoding=3, text=title)
    audio["TPE1"] = TPE1(encoding=3, text=artist)
    audio["TALB"] = TALB(encoding=3, text=album)
    audio["TRCK"] = TRCK(encoding=3, text=str(track_num))

    thumb_url = None
    try:
        thumb_url = get_apple_cover(normalize_string(album), normalize_string(artist), normalize_string(title))
    except Exception:
        thumb_url = None

    if thumb_url:
        try:
            response = retry_request(lambda: requests.get(thumb_url, timeout=10), max_retries=3)
            img_data = response.content
            mime = "image/png" if thumb_url.lower().endswith(".png") else "image/jpeg"
            audio["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_data)
        except Exception:
            pass

    try:
        slyrics, _ = fetch_lyrics(artist, title, album, get_duration_seconds(mp3_path))
        if slyrics:
            save_lrc(slyrics, mp3_path)
    except Exception:
        pass

    audio.save(mp3_path)

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
            "outtmpl": outtmpl,
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
                downloaded_path = ydl_instance.prepare_filename(info)
                if not os.path.isfile(downloaded_path) or os.path.getsize(downloaded_path) < 1024:
                    raise RuntimeError("Downloaded file missing or too small.")

                title = info.get('title', 'Unknown_Title')
                safe_title = sanitize_filename(title)
                filename = f"{safe_prefix} {safe_title}.mp3"
                full_path = os.path.join(song.folder, filename)

                try:
                    progress.update(worker_task_id, description=f"{short_desc} • converting")
                except Exception:
                    pass
                convert_to_mp3(downloaded_path, full_path)

                try:
                    os.remove(downloaded_path)
                except Exception:
                    pass

                try:
                    progress.update(worker_task_id, description=f"{short_desc} • tagging")
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
    console.print(Panel.fit("[bold cyan]YouTube Downloader[/bold cyan]", border_style="cyan"))

    urls: List[str] = []
    use_batch = console.input("Use a batch file? (y/n): ").strip().lower()
    if use_batch == "y":
        batch_file = console.input("Enter path to batch file: ").strip()
        if batch_file and os.path.isfile(batch_file):
            with open(batch_file, "r", encoding="utf-8") as f:
                urls.extend([line.strip() for line in f if line.strip() and not line.startswith("#")])
        else:
            console.print("[yellow]Batch file not found or invalid.[/yellow]")

    while True:
        url = console.input("Enter YouTube URL (or leave blank to finish): ").strip()
        if not url:
            break
        urls.append(url)

    if not urls:
        console.print("[red]No URLs provided. Exiting.[/red]")
        return

    output_dir = console.input("Enter output folder (leave empty for current directory): ").strip() or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    default_workers = min(4, (os.cpu_count() or 2))
    try:
        worker_input = console.input(f"Workers [{default_workers}]: ").strip()
        MAX_WORKERS = int(worker_input) if worker_input else default_workers
    except Exception:
        MAX_WORKERS = default_workers
    if MAX_WORKERS < 1:
        MAX_WORKERS = 1

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
