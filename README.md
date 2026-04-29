# 🎵 YouTube Audio Downloader

A fast, multi-threaded command-line tool for downloading audio from YouTube videos and playlists in **high-quality Opus format**.
It automatically expands playlists, tags tracks with metadata, fetches cover art, and saves synced lyrics when available.

---

## ✨ Features

* 🎧 **High-quality audio** in `.opus`
* ⚡ **Multi-threaded downloads** (configurable workers)
* 📜 **Playlist support** with automatic numbering
* 📂 **Batch file support** for bulk downloads
* 🧠 **Smart metadata tagging** using AcoustID + MusicBrainz
* 🖼️ **Cover art embedding** via Apple Music search
* 🎤 **Lyrics support**

  * Synced `.lrc` lyrics
  * Plain lyrics fallback
* 🧹 **Clean filenames** and organized folders
* 🎨 **Rich CLI UI** with progress bars

---

## ⚙️ Requirements

### 🐍 Python

* Python **3.8+**

### 🧰 System Dependencies

#### FFmpeg

Used for audio conversion.

* **Windows:** `winget install ffmpeg`
* **macOS:** `brew install ffmpeg`
* **Linux:** `sudo apt install ffmpeg`

#### fpcalc (AcoustID)

Used for fingerprint-based metadata.

Install from: [https://acoustid.org/](https://acoustid.org/)

---

## 📦 Installation

```bash
pip install -r requirements.txt
```

### Dependencies

* `yt-dlp`
* `mutagen`
* `musicbrainzngs`
* `requests`
* `rich`

---

## 🔑 AcoustID API Key

Set your key in the script:

```python
ACOUSTID_API_KEY = "YOUR_API_KEY_HERE"
```

Get one for free: [https://acoustid.org/](https://acoustid.org/)

> Without it, metadata lookup will be limited.

---

## 🚀 Usage

### Basic syntax

```bash
python downloader.py [URLS ...] [-b BATCH_FILE] [-o OUTPUT_DIR] [-w WORKERS]
```

---

### 🔹 Examples

#### Download a single video

```bash
python downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

#### Download a playlist

```bash
python downloader.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

#### Multiple URLs

```bash
python downloader.py URL1 URL2 URL3
```

#### Batch file

```bash
python downloader.py -b urls.txt
```

#### Custom output folder

```bash
python downloader.py -o ./Downloads
```

#### More workers

```bash
python downloader.py -w 8
```

---

## 🧾 Arguments

| Argument       | Short | Description                      | Default     |
| -------------- | ----- | -------------------------------- | ----------- |
| `urls`         | —     | YouTube URLs (video or playlist) | None        |
| `--batch-file` | `-b`  | File with URLs                   | None        |
| `--output-dir` | `-o`  | Output folder                    | Current dir |
| `--workers`    | `-w`  | Parallel downloads               | CPU-based   |

---

## 📄 Batch File Format

Example `urls.txt`:

```
# Singles
https://www.youtube.com/watch?v=abc123
https://www.youtube.com/watch?v=def456

# Playlist
https://www.youtube.com/playlist?list=PL123456
```

---

## 📂 Output Structure

### Single track

```
Output/
└── Single_Track/
    ├── 01 - Song.opus
    └── 01 - Song.lrc
```

### Playlist

```
Output/
└── Playlist Name/
    ├── 01 - Track.opus
    ├── 01 - Track.lrc
    ├── 02 - Track.opus
    └── 02 - Track.lrc
```

---

## 🏷️ Metadata

The script attempts to:

* Extract clean **title / artist**
* Match using **AcoustID fingerprint**
* Fetch metadata from **MusicBrainz**
* Embed **cover art**
* Save **lyrics**

---

## ⚠️ Notes

* Requires `ffmpeg` in PATH
* Requires `fpcalc` for fingerprinting
* Metadata depends on external databases
* Not all songs have lyrics or artwork
* YouTube titles are cleaned automatically (removes “feat.”, “remix”, etc.)

---

## 🧪 Troubleshooting

### FFmpeg not found

Install it and ensure it's in PATH.

### fpcalc not found

Install AcoustID tools.

### Missing metadata

* Check API key
* Check fpcalc
* Some tracks simply won’t match

### No lyrics

Track may not exist in LRCLib.

---

## 📜 License

MIT License – free to use, modify, and share.
