# To build it:
# docker build -t yt-dlp-docker .

# To run the cronjob:
# docker run --rm -v /mnt/Universe/Media/Ourida:/app/downloads yt-dlp-docker cronjob

# To download one 3isk video:
# docker run --rm -v /mnt/Universe/Media/Ourida:/app/downloads yt-dlp-docker 3isk <id> <url>

# To download one Aradrama video:
# docker run --rm -v /mnt/Universe/Media/Ourida:/app/downloads yt-dlp-docker aradrama <id> <url>

FROM python:3.11-slim

WORKDIR /app

COPY . .

# Codecs required for the Playwright browser to play videos
RUN apt-get update && apt-get install -y \
    libavcodec-extra \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    ffmpeg

RUN pip install .[default]

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# RUN playwright install chromium --with-deps
RUN playwright install firefox --with-deps && \
    chmod -R 777 /ms-playwright


ENTRYPOINT ["/app/mouad/docker_entrypoint.sh"]
