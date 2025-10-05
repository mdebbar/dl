import sys

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


def one_cmd(args):
    if (len(args) != 2):
        print('The `one` command requires exactly two arguments: <id> <url>')
        sys.exit(1)

    (id, url) = args

    from yt_dlp import YoutubeDL
    with YoutubeDL(['--config-location', ONE_CONFIG]) as ydl:
        # 1. Parse <id> to extract: <series>, <season_number>, <episode_number>
        # 2. Pass those as extra_info to ydl.extract_info()
        ydl.__download_wrapper(ydl.extract_info)(url, extra_info={'id': id})
        # 3. If download is successful, append the <id> to the download archive
        return ydl._download_retcode


def cronjob_cmd(args):
    if args:
        print('The `cronjob` command does not take any arguments.')
        sys.exit(1)

    import yt_dlp
    yt_dlp.main(['--config-location', CRONJOB_CONFIG])


if __name__ == '__main__':
    main(sys.argv[1:])
