#!/usr/bin/env python3
"""
Trim a phone photo of an oscilloscope screen to the screen itself, flat and at a fixed size.

Finds the screen by scanning outward from the photo centre to the dark bezel on each side, fits a
straight line to each edge, and warps the quadrilateral to a WIDTH x HEIGHT rectangle (default
1024 x 600, the SDS804X HD screen). Use it for bench photos under characterization/; a screenshot
saved by the scope itself needs no trimming.

  uv run --group bench tools/rectify_scope_photo.py IN.jpg OUT.jpg [IN2.jpg OUT2.jpg ...]
      [--size 1024x600] [--threshold 52] [--debug]

--debug also writes OUT_dbg.jpg: the photo with the detected outline, to check the corners.
Assumes the screen is brighter than the bezel around it and covers the photo centre.
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def edge_points(g, scan, indices, outward_positive, threshold, run=12):
    """For each row (or column), the first dark run of `run` pixels going out from the centre."""
    pts = []
    for i in indices:
        line = g[i, :] if scan == "row" else g[:, i]
        c = len(line) // 2
        seq = range(c, len(line)) if outward_positive else range(c, -1, -1)
        count = 0
        for j in seq:
            count = count + 1 if line[j] < threshold else 0
            if count == run:
                pts.append((i, j - (run - 1) if outward_positive else j + (run - 1)))
                break
    if len(pts) < 10:
        raise SystemExit(f"screen edge not found ({scan} scan); try another --threshold")
    return np.array(pts, float)


def fit_line(pts):
    """coord = a * i + b, refitted a few times without the worst outliers (grid lines, text)."""
    for _ in range(4):
        a, b = np.polyfit(pts[:, 0], pts[:, 1], 1)
        r = np.abs(pts[:, 1] - (a * pts[:, 0] + b))
        pts = pts[r < max(3.0, np.percentile(r, 70))]
    return a, b


def find_corners(path, threshold):
    g = np.asarray(Image.open(path).convert("L").filter(ImageFilter.BoxBlur(6)), float)
    h, w = g.shape
    rows = range(int(h * 0.3), int(h * 0.7), 4)
    cols = range(int(w * 0.25), int(w * 0.75), 4)
    left = fit_line(edge_points(g, "row", rows, False, threshold))  # x = a*y + b
    right = fit_line(edge_points(g, "row", rows, True, threshold))
    top = fit_line(edge_points(g, "col", cols, False, threshold))  # y = a*x + b
    bottom = fit_line(edge_points(g, "col", cols, True, threshold))

    def meet(v, hz):
        a, b = v
        c, d = hz
        y = (c * b + d) / (1 - c * a)
        return (a * y + b, y)

    return [meet(left, top), meet(right, top), meet(right, bottom), meet(left, bottom)]


def perspective_coeffs(dst, src):
    """Pillow PERSPECTIVE coefficients mapping output points `dst` to input points `src`."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    return np.linalg.solve(np.array(rows), np.array(rhs))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("pairs", nargs="+", help="input and output paths, in pairs")
    ap.add_argument("--size", default="1024x600", help="output WIDTHxHEIGHT (default 1024x600)")
    ap.add_argument("--threshold", type=float, default=52, help="bezel/screen grey level")
    ap.add_argument("--quality", type=int, default=85, help="JPEG quality")
    ap.add_argument("--debug", action="store_true", help="also write OUT_dbg.jpg with the outline")
    args = ap.parse_args()
    if len(args.pairs) % 2:
        ap.error("paths must come in IN OUT pairs")
    w, h = (int(v) for v in args.size.lower().split("x"))

    for src, dst in zip(args.pairs[::2], args.pairs[1::2]):
        corners = find_corners(src, args.threshold)
        print(src, "->", dst, "corners", [(round(x), round(y)) for x, y in corners])
        im = Image.open(src).convert("RGB")
        coeffs = perspective_coeffs([(0, 0), (w, 0), (w, h), (0, h)], corners)
        out = im.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
        out.save(dst, quality=args.quality, optimize=True)
        if args.debug:
            ImageDraw.Draw(im).polygon(corners, outline=(255, 0, 0), width=3)
            stem, _, ext = dst.rpartition(".")
            im.save(f"{stem}_dbg.{ext}", quality=80)


if __name__ == "__main__":
    main()
