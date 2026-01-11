#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import os
import sys
import time
import random
import subprocess
import requests
import shutil
import unicodedata
import string
from typing import Tuple, Optional

import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, USLT, TIT2, TPE1, TPE2, TALB, TRCK, error

from tqdm import tqdm
from rich.console import Console
from rich.panel import Panel

console = Console()


def sanitize_filename(name: str) -> str:

    return "".join(c if c.isalnum() or c in " _-()." else "_" for c in name).strip()


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


class DownloadProgressHook:
    def __init__(self):
        self.pbar = None

    def hook(self, d):
        if d['status'] == 'downloading':
            if not self.pbar:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                self.pbar = tqdm(total=total, unit='B', unit_scale=True, desc='Downloading')
            self.pbar.update(d['downloaded_bytes'] - self.pbar.n)
        elif d['status'] == 'finished' and self.pbar:
            self.pbar.close()
            console.print("[green]Download finished.[/green]")


def convert_to_mp3(input_path: str, output_path: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

    command = [
        'ffmpeg', '-y', '-i', input_path,
        '-vn', '-acodec', 'libmp3lame', '-b:a', '320k',
        output_path
    ]

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed:\n{result.stderr.decode()}")

    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError("Converted MP3 missing or too small.")

    console.print(f"[green]Conversion successful: {os.path.basename(output_path)}[/green]")


def download_song(url: str, output_folder: str, use_order_prefix=False, index=0):
    prefix = f"{index:02d} - " if use_order_prefix else ""
    safe_prefix = sanitize_filename(prefix)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_folder}/{safe_prefix}%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'progress_hooks': [],
    }

    hook = DownloadProgressHook()
    ydl_opts['progress_hooks'].append(hook.hook)

    def _dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            if result is None:
                raise RuntimeError("yt_dlp returned None during download.")
            return result, ydl

    info, ydl_instance = retry_request(_dl, max_retries=3)
    downloaded_path = ydl_instance.prepare_filename(info)

    if not os.path.isfile(downloaded_path) or os.path.getsize(downloaded_path) < 1024:
        raise RuntimeError("Downloaded file missing or too small.")

    title = info.get('title', 'Unknown_Title')
    safe_title = sanitize_filename(title)
    filename = f"{safe_prefix} {safe_title}.mp3"
    full_path = os.path.join(output_folder, filename)

    convert_to_mp3(downloaded_path, full_path)

    try:
        os.remove(downloaded_path)
    except Exception:
        pass

    return full_path, info

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

def normalize_string(s: str) -> str:
    if not s:
        return ""

    s = BRACKETS_RE.sub(" ", s)
    s = s.lower()
    s = s.replace("&", " and ")
    s = CLEAN_RE.sub(" ", s)

    words = [w for w in s.split() if w not in REMOVE_WORDS]

    return " ".join(words)

def get_duration_seconds(mp3_path: str) -> int:
    return int(MP3(mp3_path).info.length)

def get_apple_cover(album_name, artist_name, track_name=None):
    query_parts = [album_name, artist_name]
    if track_name:
        query_parts.insert(0, track_name)

    query = " ".join(query_parts)

    params = {
        "term": query,
        "media": "music",
        "limit": 1
    }

    response = requests.get(
        "https://itunes.apple.com/search",
        params=params,
        timeout=16
    )
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        return None

    artwork = results[0].get("artworkUrl100")
    if not artwork:
        return None

    return artwork.replace("100x100bb", "1400x1400bb")

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

    thumb_url = get_apple_cover(normalize_string(album), normalize_string(artist), normalize_string(title))

    if thumb_url:
        try:
            response = retry_request(lambda: requests.get(thumb_url, timeout=10), max_retries=3)
            img_data = response.content
            mime = "image/png" if thumb_url.lower().endswith(".png") else "image/jpeg"
            audio["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_data)
        except Exception:
            pass

    slyrics, _ = fetch_lyrics(artist, title, album, get_duration_seconds(mp3_path))
    if slyrics:
        save_lrc(slyrics, mp3_path)

    audio.save(mp3_path)

def fetch_lyrics(
    artist: str,
    title: str,
    album: str,
    duration: int,
    retries: int = 2,
    timeout: int = 20
) -> Tuple[Optional[str], Optional[str]]:

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
            console.print(params)

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

            best_match = data[0]
            return best_match.get("syncedLyrics"), best_match.get("plainLyrics")

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
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
        console.print(f"[green]✓ Saved lyrics:[/green] {os.path.basename(lrc_path)}")
        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to write lyrics:[/red] {str(e)}")
        return False

def process_song(url: str, folder: str, index: int, total: int):
    for attempt in range(1, 3):
        console.print(f"\n[bold blue][{index}/{total}] Attempt {attempt} - {url}[/bold blue]")
        try:
            mp3_path, info = download_song(url, folder, use_order_prefix=True, index=index)
            if not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) < 1024:
                raise RuntimeError("Downloaded MP3 missing or too small after conversion.")

            insert_metadata(mp3_path, info, index)
            console.print(f"[green]Finished:[/green] {os.path.basename(mp3_path)}")
            return

        except Exception as e:
            console.print(f"[red]Failed attempt {attempt}: {e}[/red]")
            if attempt == 3:
                console.print(f"[bold red]Giving up after 3 failed attempts[/bold red]")
            else:
                time.sleep(2 ** attempt)


def process_url(url: str, output_dir: str):
    with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'skip_download': True}) as ydl:
        info = retry_request(lambda: ydl.extract_info(url, download=False), max_retries=3)

    if isinstance(info, dict) and info.get('entries'):
        playlist_title = info.get('title', f'Playlist_{int(time.time())}')
        entries = [e for e in info['entries'] if e]
        folder = create_output_folder(output_dir, playlist_title)
        console.print(f"[cyan]Folder:[/cyan] {folder}")
        console.print(f"[magenta]{playlist_title}[/magenta] - {len(entries)} tracks")

        for i, entry in enumerate(entries, 1):
            video_id = entry.get('id')
            if not video_id:
                console.print(f"[yellow]Skipping entry {i}: Missing video ID[/yellow]")
                continue
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            process_song(video_url, folder, i, len(entries))

    else:
        folder = create_output_folder(output_dir, "Single_Track")
        process_song(url, folder, 1, 1)


def read_urls_from_file(file_path: str):
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def main():
    console.print(Panel.fit("[bold cyan]YouTube Music Downloader[/bold cyan]", border_style="cyan"))

    urls = []
    use_batch = input("Use a batch file? (y/n): ").strip().lower()
    if use_batch == "y":
        batch_file = input("Enter path to batch file: ").strip()
        urls.extend(read_urls_from_file(batch_file))

    while True:
        url = input("Enter YouTube URL (or leave blank to finish): ").strip()
        if not url:
            break
        urls.append(url)

    if not urls:
        console.print("[red]No URLs entered. Exiting.[/red]")
        return

    output_dir = input("Enter output folder (leave empty for current directory): ").strip()
    if not output_dir:
        output_dir = os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    console.print(f"\nProcessing [bold]{len(urls)}[/bold] URL(s)")
    console.print(f"[bold yellow]Output directory: {output_dir}[/bold yellow]")

    for i, url in enumerate(urls, 1):
        console.rule(f"[bold green]Processing URL {i}/{len(urls)}[/bold green]")
        process_url(url, output_dir)

    console.print(Panel.fit("[bold green]All downloads completed![/bold green]", border_style="green"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Cancelled by user[/red]")
        sys.exit(1)
