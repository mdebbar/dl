#!/usr/bin/env bash


# Name of the TV Show e.g. "Uzak Sehir"
NAME="$1"

# Season and Episode e.g. "01x21"
SEASON_EPISODE="$2"

# URL of the video or m3u8 file to download.
DOWNLOAD_URL="$3"

# Download isn't useful since these downloads don't have the right ID.
# --download-archive /app/downloads/downloaded.txt \

docker run \
  --rm \
  -v /mnt/Universe/Media/Ourida:/app/downloads \
  yt-dlp-docker \
  -N 8 \
  --proxy "socks5://10.10.10.10:1080" \
  --fixup never \
  -o "/app/downloads/$NAME/$NAME $SEASON_EPISODE.%(ext)s" \
  --no-config \
  "$DOWNLOAD_URL"