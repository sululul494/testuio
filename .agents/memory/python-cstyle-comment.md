---
name: Python C-style comments
description: C-style `//` comments in Python cause a SyntaxError on import; check for them after pulling external code.
---

# Python C-style comments

## Rule
After importing code from another project or editing Python files, always grep for `//` inside `.py` files. Python does not accept `//` as a comment; it is the floor-division operator. A stray `//` will crash the app at startup with a `SyntaxError`.

**Why:** This happened in `app/ffmpeg/streamer.py` after a previous edit, causing the FastAPI process to fail before the `/health` endpoint could respond.

**How to apply:**
- Run `grep -R "//" app/ --include="*.py"` after any external import or hand-off.
- Replace any `//` comments with `#`.
