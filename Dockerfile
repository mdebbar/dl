# To build it:
# docker build -t yt-dlp-docker .

# To run it:
# docker run --rm -v /path/to/downloads:/app/downloads yt-dlp-docker -P /app/downloads

FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install .[default]

ENTRYPOINT ["/app/yt-dlp.sh"]