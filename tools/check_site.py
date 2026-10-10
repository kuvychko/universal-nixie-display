"""Checks on the built companion site that the strict build does not make.

Run:  uv run --group docs mkdocs build --strict && uv run python tools/check_site.py

1. **Subpath safety:** no root-relative ``href`` or ``src`` (``"/..."``). The site is served
   under ``/universal-nixie-display/``, where those would break.
2. **Images:** every ``<img>`` has non-empty alt text, and every local image exists.
3. **Page weight:** the largest pages by total image size are listed, so heavy pages are visible.
4. **External links:** listed for a manual check. GitHub links to the repository return 404
   until the repository is public.

Exits 1 if checks 1 or 2 fail.
"""

import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITE = Path(__file__).resolve().parents[1] / "site"


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img":
            self.images.append((a.get("src", ""), a.get("alt")))
        if tag in ("link", "script") and (a.get("href") or a.get("src")):
            self.links.append(a.get("href") or a.get("src"))


def main() -> None:
    if not SITE.is_dir():
        sys.exit("build the site first: uv run --group docs mkdocs build --strict")
    problems, external, weights = [], Counter(), {}
    for page in sorted(SITE.rglob("*.html")):
        if page.name == "404.html":
            continue
        rel = page.relative_to(SITE).as_posix()
        c = Collector()
        c.feed(page.read_text(encoding="utf-8"))
        for url in c.links:
            if url.startswith("/") and not url.startswith("//"):
                problems.append(f"{rel}: root-relative link {url}")
            elif urlparse(url).scheme in ("http", "https"):
                external[url] += 1
        total = 0
        for src, alt in c.images:
            if src.startswith("/") and not src.startswith("//"):
                problems.append(f"{rel}: root-relative image {src}")
            if not alt or not alt.strip():
                problems.append(f"{rel}: image without alt text: {src}")
            if urlparse(src).scheme:
                continue
            target = (page.parent / urlparse(src).path).resolve()
            target = (
                Path(urljoin(page.as_posix(), urlparse(src).path))
                if not target.exists()
                else target
            )
            if not target.exists():
                problems.append(f"{rel}: missing image {src}")
            else:
                total += target.stat().st_size
        weights[rel] = total

    print("heaviest pages (images):")
    for rel, size in sorted(weights.items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {size / 1e6:5.2f} MB  {rel}")
    print("external links (check by hand; repository links work once it is public):")
    own = "https://kuvychko.github.io/universal-nixie-display/"  # canonical tags
    for url in sorted(u for u in external if not u.startswith(own)):
        print(f"  {url}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    print("\nsubpath links, alt text and local images: OK")


if __name__ == "__main__":
    main()
