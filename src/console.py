"""Force UTF-8 stdio so operator-facing console/log output (checkmarks,
arrows, emoji) never crashes when stdout/stderr aren't a real console --
e.g. redirected to a file (scheduler/run_daily.bat's `>> logs\\workflow.log`)
or piped through subprocess.run(capture_output=True).
"""

import sys


def force_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8, replacing characters that can't
    be encoded rather than raising UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
