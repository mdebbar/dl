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

RUN pip install .[default] \
    && playwright install chromium --with-deps \
    && playwright install firefox --with-deps

ENTRYPOINT ["/app/mouad/docker_entrypoint.sh"]
