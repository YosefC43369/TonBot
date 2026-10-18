# root-level entry wrapper — panel runs this via PY_FILE=main.py
import asyncio
import os
import sys

# guarantee project root is on path regardless of how python was invoked
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())