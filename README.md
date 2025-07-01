---

## 🎵 YouTube Music Downloader (MP3 with Metadata + Lyrics)

A terminal-based Python tool to **download YouTube songs or playlists as high-quality MP3s**, with optional **metadata, cover art, and synced lyrics**.

---

### ✅ Features

* Download individual videos or full playlists
* Convert to 320kbps MP3 using `yt-dlp` + `ffmpeg`
* Embed metadata (title, artist, album)
* Embed high-res thumbnail as cover art
* Auto-fetch synced and unsynced lyrics from LRCLib
* Save lyrics as `.lrc` alongside MP3
* Fully interactive CLI (no arguments, just input prompts)

---

### 📦 Requirements

* Python 3.8+
* `ffmpeg` installed and in your PATH
* Install dependencies with:

```bash
pip install -r requirements.txt
```

---

### 📥 Usage

Just run the script — it will guide you step-by-step:

```bash
python g.py
```

You'll be prompted for:

* A batch file (optional)
* YouTube links (one or more)
* Output folder
* Whether to include metadata
* Whether to include cover art
* Whether to fetch lyrics

---

### 📁 Batch File Format

If using a batch file:

* One URL per line
* Lines starting with `#` are ignored

Example (`urls.txt`):

```
https://www.youtube.com/watch?v=abc123
https://www.youtube.com/playlist?list=xyz456
# This is a comment
```

---

### 🛠 Output

Each song or playlist will be saved in a clean folder structure like:

```
output_dir/
└── PlaylistName/
    ├── Song Title.mp3
    ├── Song Title.lrc  (if lyrics found)
```

---

### 💡 Notes

* Cover art is extracted from the highest-resolution thumbnail available.
* Lyrics fetched from [lrclib.net](https://lrclib.net/).
* Script uses `yt-dlp`, `mutagen`, `requests`, `rich`, and `tqdm`.

---

### 🧾 License

MIT License — free to use, modify, and share.

---
