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
    import yt_dlp
    yt_dlp.main(args)

if __name__ == '__main__':
    main(sys.argv[1:])
