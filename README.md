# 🎵 YT-Music-DL

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![GitHub last commit](https://img.shields.io/github/last-commit/yourusername/YT-Music-DL)

A feature-rich YouTube music downloader that converts videos to high-quality MP3s with complete metadata, cover art, and synchronized lyrics.

![Demo Screenshot](https://i.imgur.com/example.png) *(example screenshot placeholder)*

## ✨ Features

- **High Quality Audio**: 320kbps MP3 conversion
- **Smart Metadata**:
  - Automatic title, artist, and album tagging
  - Cover art embedding from YouTube thumbnails
- **Lyrics Support**:
  - Fetches time-synced lyrics (LRC format)
  - Embeds plain lyrics in MP3 files
- **Batch Processing**:
  - Download entire playlists with one command
  - Process multiple URLs or text files
- **Beautiful Interface**:
  - Rich terminal formatting
  - Progress bars for downloads
  - Color-coded status messages

## ⚙️ Installation

1. **Prerequisites**: Python 3.8+
```bash
# Verify Python version
python --version
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## 🚀 Usage

### Basic Commands
```bash
# Single video
python yt_music.py "https://youtube.com/watch?v=..."

# Playlist
python yt_music.py "https://youtube.com/playlist?list=..."

# Multiple URLs
python yt_music.py "https://url1" "https://url2" "https://url3"
```

### Advanced Options
```bash
# Custom output directory
python yt_music.py -o ~/Music/ "https://url"

# Batch processing from file
python yt_music.py --batch-file=urls.txt

# Disable features
python yt_music.py --no-cover --no-lyrics "https://url"
```

### Batch File Format (urls.txt)
```text
# Comments are allowed
https://youtube.com/playlist?list=PL...
https://youtube.com/watch?v=...
# More URLs...
```

## 📂 Output Structure
```
Output_Directory/
├── Playlist_Name/
│   ├── Song_Title.mp3
│   ├── Song_Title.lrc (if lyrics found)
│   └── ...
└── Single_Tracks/
    └── Song_Title.mp3
```

## 🛠️ Configuration
Customize behavior by modifying these default options in the script:
- Default download quality
- Metadata preferences
- Retry attempts
- Timeout settings

## 🤝 Contributing
Pull requests are welcome! For major changes, please open an issue first.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


