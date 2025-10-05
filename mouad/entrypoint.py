import re
import string
import sys
from urllib.parse import urlparse

CRONJOB_CONFIG = '/app/mouad/ytdlp_cronjob.conf'
ONE_CONFIG = '/app/mouad/ytdlp_one.conf'

def main(args):
    cmd = args.pop(0)

    match cmd:
        case 'cronjob':
            return cronjob_cmd(args)
        case 'one':
            return one_cmd(args)
        case _:
            print(f'Unknown command: {cmd}')
            print('Available commands: one, cronjob')
            sys.exit(1)



def cronjob_cmd(args):
    if args:
        print('The `cronjob` command does not take any arguments.')
        sys.exit(1)

    import yt_dlp
    yt_dlp.main(['--config-location', CRONJOB_CONFIG])


def one_cmd(args):
    if (len(args) != 2):
        print('The `one` command requires exactly two arguments: <id> <url>')
        sys.exit(1)

    (id, url) = args

    ID_RE = r'serie-(?P<series>[\w-]+?)-season-(?P<season>\d+)-episode-(?P<episode>\d+)'
    if not re.match(ID_RE, id):
        print(f'Invalid id: {id}')
        print('Expected format: serie-<series>-season-<season_number>-episode-<episode_number>')
        sys.exit(1)

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print(f'Invalid url: {url}')
        sys.exit(1)

    from yt_dlp import YoutubeDL, parse_options
    _, __, ___, ydl_opts = parse_options(['--config-location', ONE_CONFIG])
    with YoutubeDL(ydl_opts) as ydl:
        mobj = re.match(ID_RE, id)
        series = string.capwords(mobj.group('series').replace('-', ' '))
        season = mobj.group('season').zfill(2)
        episode = mobj.group('episode').zfill(2)
        ydl.extract_info(url, extra_info={
            'id': id,
            'series': series,
            'season': season,
            'episode': episode,
        })
        if ydl._download_retcode == 0:
            with open('/app/downloads/downloaded.txt', 'a') as f:
                f.write(f'iskepisode {id}\n')
        return ydl._download_retcode



if __name__ == '__main__':
    main(sys.argv[1:])
