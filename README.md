# 🎵 YouTube Music Downloader

A robust, multi-threaded command-line tool to download YouTube videos and playlists as high-quality 320kbps MP3s. It automatically fetches and embeds ID3 metadata, high-resolution cover art, and synced lyrics.

## ✨ Key Features

* **High-Quality Audio:** Extracts and converts audio to 320kbps MP3 using `yt-dlp` and `FFmpeg`.
* **Smart Metadata:** Cleans up track titles and attempts to fetch accurate metadata (Artist, Title, Album).
* **HD Cover Art:** Automatically searches and embeds high-resolution album artwork via the Apple Music API.
* **Synced Lyrics:** Fetches synced (`.lrc`) or unsynced lyrics via [LRCLib](https://lrclib.net/) and embeds/saves them alongside the audio.
* **Multi-Threaded:** Lightning-fast concurrent downloads using a customizable number of background workers.
* **Beautiful CLI:** Real-time, responsive terminal progress bars powered by `Rich`.
* **Batch Processing:** Pass individual URLs, full playlists, or a `.txt` file containing multiple links.

---

## ⚙️ Installation

### 1. Prerequisites

You must have **Python 3.8+** and **FFmpeg** installed on your system.

* **Windows:** Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or install via winget: `winget install ffmpeg`
* **macOS:** Install via Homebrew: `brew install ffmpeg`
* **Linux:** Install via APT: `sudo apt install ffmpeg`

### 2. Install Dependencies

Clone the repository and install the required Python packages:

```bash
pip install -r requirements.txt

```

*(Dependencies include: `yt-dlp`, `mutagen`, `requests`, `rich`)*

---

## 🚀 Usage

The script is entirely driven by command-line arguments, making it easy to automate or run as a background task.

### Basic Syntax

```bash
python downloader.py [URLS ...] [-o OUTPUT_DIR] [-b BATCH_FILE] [-w WORKERS]

```

### Examples

**1. Download a single song:**

```bash
python downloader.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"

```

**2. Download a full playlist to a specific folder using 8 workers:**

```bash
python downloader.py "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID" -o ./MyMusic -w 8

```

**3. Download from a text file:**

```bash
python downloader.py -b urls.txt -o ./Downloads

```

### Available Arguments

| Argument | Short | Description | Default |
| --- | --- | --- | --- |
| `urls` |  | One or more YouTube URLs (videos or playlists) separated by spaces. | `None` |
| `--output-dir` | `-o` | The directory where downloaded folders will be saved. | Current Directory |
| `--batch-file` | `-b` | Path to a text file containing YouTube URLs. | `None` |
| `--workers` | `-w` | Number of concurrent download threads. | `4` (or CPU count) |
| `--help` | `-h` | Show the help menu and exit. |  |

---

## 📝 Batch File Format

If you use the `-b` or `--batch-file` flag, provide a standard text file with one URL per line. The script will automatically ignore blank lines and comments (lines starting with `#`).

**Example (`urls.txt`):**

```text
# Synthwave tracks
https://www.youtube.com/watch?v=abc12345
https://www.youtube.com/watch?v=xyz09876

# Lo-Fi Playlist
https://www.youtube.com/playlist?list=PL1234567890

```

---

## 📂 Output Structure

The script keeps your music organized. Single tracks are placed in a `Single_Track` folder, while playlists are saved in a folder named after the YouTube playlist.

```text
📁 Output_Directory/
├── 📁 Single_Track/
│   ├── 01 - Song Title.mp3
│   └── 01 - Song Title.lrc         <-- (If synced lyrics are found)
└── 📁 Vibes Playlist/
    ├── 01 - First Song.mp3
    ├── 02 - Second Song.mp3
    └── 02 - Second Song.lrc

```

---

## 🧾 License

Distributed under the MIT License. Free to use, modify, and share.
