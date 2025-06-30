#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import random
import argparse
import requests
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, USLT, TIT2, TPE1, TALB, error
from tqdm import tqdm

# Rich CLI helpers
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

console = Console()

# Utility helpers
def create_output_folder(base_path: str, name: str) -> str:
    """Create a safe output folder name"""
    safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    folder_path = os.path.join(base_path, safe_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def retry_request(func, max_retries=3, backoff_factor=2, *args, **kwargs):
    """Retry a function with exponential backoff"""
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
    """Bridge yt-dlp progress messages to tqdm bar"""
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
            console.print("[green]Download finished, converting to MP3...[/green]")

def download_song(url: str, output_folder: str):
    """Download and convert a YouTube video to MP3"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_folder}/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'progress_hooks': [],
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
    }
    hook = DownloadProgressHook()
    ydl_opts['progress_hooks'].append(hook.hook)

    def _dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=True)

    info = retry_request(_dl, max_retries=3)
    if info is None:
        raise RuntimeError("Download failed or info missing.")
    title = info.get('title', 'Unknown_Title')
    return os.path.join(output_folder, f"{title}.mp3"), info

def get_duration_seconds(mp3_path: str) -> int:
    """Get duration of MP3 file in seconds"""
    return int(MP3(mp3_path).info.length)

def fetch_lyrics(artist, title, album, duration):
    """Fetch lyrics from LRCLib API"""
    def _fetch():
        q = {
            "artist_name": artist,
            "track_name": title,
            "album_name": album,
            "duration": str(duration)
        }
        res = requests.get("https://lrclib.net/api/search", params=q, timeout=10)
        res.raise_for_status()
        return res.json()

    try:
        data = retry_request(_fetch, max_retries=3)
        if not data:
            return None, None
        return data[0].get("syncedLyrics"), data[0].get("plainLyrics")
    except Exception as e:
        console.print(f"[yellow]Failed to fetch lyrics: {e}[/yellow]")
        return None, None

def save_lrc(lyrics: str, mp3_path: str):
    """Save lyrics to LRC file"""
    lrc_path = os.path.splitext(mp3_path)[0] + ".lrc"
    with open(lrc_path, "w", encoding="utf-8") as f:
        f.write(lyrics)
    console.print(f"[green]Saved LRC:[/green] {os.path.basename(lrc_path)}")

def insert_metadata(mp3_path: str, info: dict, plain_lyrics: str | None,
                    include_meta: bool, include_cover: bool):
    """Embed metadata into MP3 file"""
    try:
        audio = ID3(mp3_path)
    except error.ID3NoHeaderError:
        audio = ID3()

    # Basic tags
    if include_meta:
        audio["TIT2"] = TIT2(encoding=3, text=info.get("title", "Unknown Title"))
        audio["TPE1"] = TPE1(encoding=3, text=info.get("artist") or info.get("uploader") or "Unknown Artist")
        audio["TALB"] = TALB(encoding=3, text=info.get("album") or "Unknown Album")

    # Lyrics
    if plain_lyrics:
        audio["USLT"] = USLT(encoding=3, desc="Lyrics", text=plain_lyrics)

    # Cover art
    if include_cover:
        thumb_url = info.get("thumbnail")
        if not thumb_url and "thumbnails" in info:
            thumbs = info["thumbnails"]
            if thumbs:
                thumb_url = sorted(thumbs, key=lambda t: t.get("height", 0), reverse=True)[0].get("url")

        if thumb_url:
            try:
                response = retry_request(lambda: requests.get(thumb_url, timeout=10), max_retries=3)
                img_data = response.content
                
                # Remove size validation since some valid covers might be small
                mime = "image/png" if thumb_url.lower().endswith(".png") else "image/jpeg"
                audio["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_data)
                console.print("[green]Embedded cover art[/green]")
            except Exception as e:
                console.print(f"[yellow]Cover art skipped: {e}[/yellow]")
        else:
            console.print("[yellow]No cover art URL found[/yellow]")

    audio.save(mp3_path)
    console.print("[green]Metadata saved[/green]")

def process_song(url: str, folder: str, index: int, total: int,
                include_meta: bool, include_cover: bool, include_lyrics: bool):
    """Process a single song"""
    console.print(f"\n[bold blue][{index}/{total}] Downloading:[/bold blue] {url}")
    try:
        mp3_path, info = download_song(url, folder)
    except Exception as e:
        console.print(f"[red]Download failed: {e}[/red]")
        return

    title = info.get("title", "Unknown Title")
    artist = info.get("artist") or info.get("uploader") or "Unknown Artist"
    album = info.get("album") or "Unknown Album"

    console.print(f"[bold]{title}[/bold] • [italic]{artist}[/italic] • {album}")

    try:
        duration = get_duration_seconds(mp3_path)
    except Exception as e:
        console.print(f"[yellow]Couldn't get duration: {e}[/yellow]")
        duration = 0

    plain_lyrics = None
    if include_lyrics:
        try:
            synced, plain_lyrics = fetch_lyrics(artist, title, album, duration)
            if synced:
                save_lrc(synced, mp3_path)
            else:
                console.print("[yellow]No synced lyrics found[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Lyrics fetch failed: {e}[/yellow]")

    if include_meta or include_cover or (include_lyrics and plain_lyrics):
        try:
            insert_metadata(mp3_path, info, plain_lyrics, include_meta, include_cover)
        except Exception as e:
            console.print(f"[red]Metadata embedding failed: {e}[/red]")

def process_url(url: str, output_dir: str, include_meta: bool, 
               include_cover: bool, include_lyrics: bool):
    """Process a URL (playlist or single track)"""
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'skip_download': True}) as ydl:
            info = retry_request(lambda: ydl.extract_info(url, download=False), max_retries=3)

        # Playlist
        if isinstance(info, dict) and info.get('entries'):
            playlist_title = info.get('title', f'Playlist_{int(time.time())}')
            entries = [e for e in info['entries'] if e]
            folder = create_output_folder(output_dir, playlist_title)
            console.print(f"[cyan]Folder:[/cyan] {folder}")
            console.print(f"[magenta]{playlist_title}[/magenta] - {len(entries)} tracks")

            for i, entry in enumerate(entries, 1):
                if not entry:
                    continue
                    
                video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                try:
                    process_song(video_url, folder, i, len(entries),
                                 include_meta, include_cover, include_lyrics)
                except Exception as e:
                    console.print(f"[red]Skipping track {i}: {e}[/red]")

        # Single track
        else:
            single_title = info.get('title', 'Single')
            folder = create_output_folder(output_dir, single_title)
            process_song(url, folder, 1, 1, include_meta, include_cover, include_lyrics)

    except Exception as e:
        console.print(f"[red]Failed to process URL: {e}[/red]")

def read_urls_from_file(file_path: str):
    """Read URLs from a text file"""
    try:
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        console.print(f"[red]Error reading batch file: {e}[/red]")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description='YouTube Music Downloader - Download playlists or individual tracks with metadata',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('urls', nargs='*', help='YouTube URLs to download')
    parser.add_argument('-b', '--batch-file', help='File containing list of URLs to download (one per line)')
    parser.add_argument('-o', '--output-dir', default=os.getcwd(), 
                       help='Output directory for downloads')
    parser.add_argument('--no-meta', action='store_false', dest='meta',
                       help='Skip embedding metadata (title/artist/album)')
    parser.add_argument('--no-cover', action='store_false', dest='cover',
                       help='Skip embedding cover art')
    parser.add_argument('--no-lyrics', action='store_false', dest='lyrics',
                       help='Skip fetching lyrics')
    parser.add_argument('--version', action='version', version='%(prog)s 2.0')
    
    args = parser.parse_args()

    console.print(Panel.fit("[bold cyan]YouTube Music Downloader[/bold cyan]", border_style="cyan"))

    # Collect URLs from all sources
    urls = args.urls
    if args.batch_file:
        urls.extend(read_urls_from_file(args.batch_file))
    
    if not urls:
        console.print("[red]No URLs provided. Use command-line arguments or --batch-file.[/red]")
        parser.print_help()
        return

    console.print(f"Processing [bold]{len(urls)}[/bold] URLs")
    console.print(f"Output directory: [cyan]{args.output_dir}[/cyan]")
    console.print(f"Metadata: {'[green]Enabled[/green]' if args.meta else '[yellow]Disabled[/yellow]'}")
    console.print(f"Cover art: {'[green]Enabled[/green]' if args.cover else '[yellow]Disabled[/yellow]'}")
    console.print(f"Lyrics: {'[green]Enabled[/green]' if args.lyrics else '[yellow]Disabled[/yellow]'}")

    # Create output directory if needed
    os.makedirs(args.output_dir, exist_ok=True)

    # Process each URL
    for i, url in enumerate(urls, 1):
        console.rule(f"[bold green]Processing URL {i}/{len(urls)}[/bold green]")
        try:
            process_url(url, args.output_dir, args.meta, args.cover, args.lyrics)
        except Exception as e:
            console.print(f"[red]Fatal error processing URL: {e}[/red]")
        console.print("")

    console.print(Panel.fit("[bold green]All downloads completed![/bold green]", border_style="green"))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Operation cancelled by user[/red]")
        sys.exit(1)
