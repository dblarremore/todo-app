#!/bin/bash
# Double-click to start/open the shared Todo app. Errors stay visible in Terminal.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required. Install it, then launch Todo again."
    exit 1
fi
python3 launch.py "$@"
