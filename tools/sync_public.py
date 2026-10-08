"""
Copy the dashboard front end from app/static into public/.

app/static is the source of truth: that is what `python run.py` serves and what
you edit. public/ is the deploy copy — on Vercel, files under public/ are served
straight off the CDN, so the React shell and its assets need to exist there too.

    python tools/sync_public.py          # copy
    python tools/sync_public.py --check  # exit 1 if the copies have drifted

Run it after changing anything under app/static, and commit both trees.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "static"
DST = ROOT / "public"

# index.html sits at the root of public/ because Vercel serves public/ at "/".
# Everything it references lives under /static/, which is both the FastAPI
# mount point and the path these files take inside public/.
COPIES = [
    ("index.html", "index.html"),
    ("assets", "assets"),
    ("assets", "static/assets"),
]


def iter_pairs():
    """(source file, destination file) for everything in COPIES."""
    for src_rel, dst_rel in COPIES:
        src, dst = SRC / src_rel, DST / dst_rel
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    yield f, dst / f.relative_to(src)
        else:
            yield src, dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report drift instead of copying")
    args = ap.parse_args()

    drift, copied = [], 0
    for src, dst in iter_pairs():
        same = dst.exists() and filecmp.cmp(src, dst, shallow=False)
        if same:
            continue
        if args.check:
            drift.append(dst.relative_to(ROOT))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    # A file left behind in public/ that no longer exists in app/static would be
    # served as a stale module, so say so.
    wanted = {dst for _, dst in iter_pairs()}
    for _, dst_rel in COPIES:
        root = DST / dst_rel
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and f not in wanted:
                if args.check:
                    drift.append(f.relative_to(ROOT))
                else:
                    f.unlink()
                    print(f"removed stale {f.relative_to(ROOT)}")

    if args.check:
        if drift:
            print("public/ is out of date:")
            for d in drift:
                print(f"  {d}")
            print("\nrun: python tools/sync_public.py")
            return 1
        print("public/ matches app/static")
        return 0

    print(f"synced {copied} file(s) from app/static to public/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
