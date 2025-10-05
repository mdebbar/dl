import sys

def main(args):
    cmd = args.pop(0)

    match cmd:
        case 'one':
            return one_cmd(args)
        case 'cronjob':
            return cronjob_cmd(args)
        case _:
            print(f'Unknown command: {cmd}')
            print('Available commands: one, cronjob')
            sys.exit(1)


def one_cmd(args):
    print('Running command `one` with args:', args)


def cronjob_cmd(args):
    if args:
        print('The `cronjob` command does not take any arguments.')
        sys.exit(1)

    import yt_dlp
    yt_dlp.main(['--config-location', '/app/mouad/cronjob.conf'])


if __name__ == '__main__':
    main(sys.argv[1:])
