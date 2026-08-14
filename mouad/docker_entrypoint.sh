#!/usr/bin/env sh

if [ -z "$HOME" ] || [ "$HOME" = "/" ]; then
    export HOME=/tmp
fi
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

exec "${PYTHON:-python3}" -Werror -Xdev "$(dirname "$(realpath "$0")")/entrypoint.py" "$@"

