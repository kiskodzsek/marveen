#!/usr/bin/env python3
"""reel-size-gate: the product keeps the opening shot's size all through a 9:16 reel, and nothing is cut at the bottom.

Why (Patrik csoport TG 5798, 2026-11-13, on the Meséld el! reel v10c): "7-8 masodperc utan emgint kicsi minden levagott az
alba miert nem vegig a jo meret van". The v10c passed every other gate (film-kapu, kép-kapu, OCR) and still went out with a
658 px closed book after an 888 px spread, and with a book whose bottom the source render had cut (Klodel 40331: UGYANAZ A
HIBA KÉTSZER NEM -> a machine gate before the export).

Usage: python3 -I reel-size-gate.py <video.mp4 | frames-dir> [--end 24] [--skip 7.5,..] [--zone 512,1165]
  video: one frame per second at t = 0.5, 1.5, ... (ffmpeg); frames-dir: t_<sec>.png files from render.mjs frames
  --end   the last product second (the closing title card carries no product and is not measured)
  --skip  seconds that are an intentional dip/cross-fade (the product is fading on purpose), listed one by one
  --zone  the product zone, y from..to: under the caption, above the bottom pill (v10c/v10d layout)
Exit: 0 = every measured second keeps the size and no bottom is cut; 1 = a second fails (one line each on stderr), or no
second was measured at all; 2 = usage (an unknown option or a missing value).

Measured per second, in the zone:
  the product = the rows with >= 6 strong-edge pixels (|dx|+|dy| of the gray image > 40; the soft bokeh stays under it),
  minus a short (<= 75 px) block on top that stands >= 12 px clear (the chips row, a caption descender); the reference is
  the first second.
  FILL: the same scale as the opening, in the object's own limiting dimension:
        a landscape/square object (a spread, the closed book): height >= 95 % of the opening's (the width alone is not
        enough: v10e's flatter 19-23.5 s spread was 891 px wide like the opening but 491 px high vs 551 -> "kisebb",
        independent review 2026-11-13);
        a portrait object (h > 1.3 w, the phone): height >= 105 % of the opening's (a phone only as tall as the spread
        reads small: v10c's 317x549 phone next to the 889x551 spread was Patrik's "kicsi").
        Calibrated: v10c closed book 658x483 (74 %/88 %) and phone 549 px (100 %) -> fail (Patrik TG 5798);
        v10d/v10e closed book 680x543 (99 % height) and phone 349x611 (111 %) -> pass (not yet judged by Patrik).
  CUT:  touching the frame side, or the bright paper (gray > 170) ending in one dead-level row: if >= 55 % of the paper
        columns (and >= 300 px) end on the same row (+-1 px), the source or the window cut the book there.
"""
import os
import re
import subprocess
import sys

import numpy as np

W, H = 1080, 1920


def frame_from_video(path, t):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', path, '-frames:v', '1', '-f', 'rawvideo',
                          '-pix_fmt', 'gray', '-s', f'{W}x{H}', '-'], capture_output=True, check=True).stdout
    if len(raw) != W * H:
        return None
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.int16)


def frame_from_png(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', f'{W}x{H}', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.int16)


def runs(idx, gap=10):
    out, a = [], None
    for i in idx:
        if a is None:
            a = b = i
        elif i - b <= gap:
            b = i
        else:
            out.append((a, b)); a = b = i
    if a is not None:
        out.append((a, b))
    return out


def measure(g, z0, z1):
    z = g[z0:z1]
    e = np.zeros_like(z, dtype=bool)
    e[:, 1:] |= np.abs(np.diff(z, axis=1)) > 40
    e[1:, :] |= np.abs(np.diff(z, axis=0)) > 40
    rr = runs(np.where((e.sum(1) >= 6) | ((z > 170).sum(1) >= 6))[0], gap=6)  # edge rows or paper/screen rows
    # a short block on top, clear of the rest, is the chips row or a caption descender, not the product
    while len(rr) > 1 and rr[0][1] - rr[0][0] <= 75 and rr[1][0] - rr[0][1] >= 12:
        rr = rr[1:]
    if not rr:
        return None
    r0, r1 = rr[0][0], rr[-1][1]
    cols = np.where((e[r0:r1 + 1].sum(0) >= 6) | ((z[r0:r1 + 1] > 170).sum(0) >= 6))[0]
    if not len(cols):
        return None
    box = (int(cols[0]), r0 + z0, int(cols[-1]), r1 + z0)
    paper = z > 170
    has = paper.any(0)
    cut = None
    if box[0] <= 1 or box[2] >= W - 2:
        cut = ('side', box[0] if box[0] <= 1 else box[2])
    elif has.sum() >= 300:
        bottoms = (z.shape[0] - 1 - np.argmax(paper[::-1], axis=0))[has]
        vals, counts = np.unique(bottoms, return_counts=True)
        best = max(range(len(vals)), key=lambda i: counts[max(0, i - 1):i + 2].sum())
        level = counts[max(0, best - 1):best + 2].sum()
        if level >= 300 and level >= .55 * has.sum():
            cut = ('bottom', int(vals[best]) + z0, int(level))
    return box, cut


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith('-'):
        print(__doc__, file=sys.stderr)
        return 2
    src = a[0]
    # Viktor 41284 (2): a mistyped option (--zon) or a missing value must not fall away silently
    rest = a[1:]
    if len(rest) % 2 or any(k not in ('--end', '--skip', '--zone') for k in rest[0::2]):
        print(f'REEL-SIZE-GATE: unknown option or missing value in {rest} (allowed: --end N --skip a,b --zone y1,y2)',
              file=sys.stderr)
        return 2
    opt = {k: v for k, v in zip(rest[0::2], rest[1::2])}
    end = float(opt.get('--end', 1e9))
    skip = {round(float(x), 2) for x in opt.get('--skip', '').split(',') if x}
    z0, z1 = (int(x) for x in opt.get('--zone', '512,1165').split(','))
    if os.path.isdir(src):
        items = []
        for f in os.listdir(src):
            m = re.fullmatch(r't_(\d+(?:\.\d+)?)\.png', f)
            if m:
                items.append((float(m.group(1)), os.path.join(src, f)))
        frames = [(t, frame_from_png(p)) for t, p in sorted(items)]
    else:
        dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src],
                                   capture_output=True, text=True, check=True).stdout)
        frames = [(t + .5, frame_from_video(src, t + .5)) for t in range(int(dur))]
    ref, errs, n = None, [], 0
    for t, g in frames:
        if g is None or t > end or round(t, 2) in skip:
            continue
        m = measure(g, z0, z1)
        if m is None:
            errs.append(f'{t:5.1f} s: no product in the zone y {z0}-{z1}')
            continue
        (x0, y0, x1, y1), cut = m
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if ref is None:
            ref = (x0, y0, x1, y1, w, h)
            print(f'REF {t:.1f} s: box x {x0}-{x1}, y {y0}-{y1} ({w}x{h})')
        n += 1
        fh, fw = h / ref[5], w / ref[4]
        fill = fh >= 1.05 if h > 1.3 * w else fh >= .95
        line = f'{t:5.1f} s: box x {x0}-{x1}, y {y0}-{y1} ({w}x{h}; opening height {fh:.0%}, opening width {fw:.0%})'
        if not fill:
            errs.append(f'{line} -> SMALLER than the opening')
        if cut:
            errs.append(f'{line} -> CUT at the ' + (f'frame side x {cut[1]}' if cut[0] == 'side' else f'bottom: {cut[2]} paper columns end on row y {cut[1]}'))
        if fill and not cut:
            print(f'{line} ok')
    if errs:
        print('REEL-SIZE-GATE: NOT OK (Patrik TG 5798: "nem vegig a jo meret", "levagott az alja"):', file=sys.stderr)
        for e in errs:
            print('  - ' + e, file=sys.stderr)
        return 1
    if n == 0:
        # Viktor 41284 (2): an empty frames dir, wrong file names (only t_<sec>.png), --end 0 or every second in --skip
        # measured nothing and still said "ok"; as a gate that is a pass without a measurement.
        print('REEL-SIZE-GATE: NOT OK: no measurable frame (frames dir empty, names not t_<sec>.png, --end 0, or every '
              'second in --skip)', file=sys.stderr)
        return 1
    print(f'REEL-SIZE-GATE: ok, {n} seconds measured')
    return 0


if __name__ == '__main__':
    sys.exit(main())
