"""Deterministic spike-local bitmap images and exact exposure verification."""

import csv
import struct
import zlib
from pathlib import Path

from bicentennial.keyed import shuffle, uniform_int

WIDTH, HEIGHT = 480, 320
SIGNATURE = b"\x89PNG\r\n\x1a\n"
FAMILIES = {
    "F0": ((245, 245, 240), (20, 25, 30), (35, 90, 140)),
    "F1": ((20, 30, 45), (245, 245, 235), (80, 160, 210)),
    "F2": ((250, 240, 215), (45, 30, 15), (145, 70, 25)),
    "F3": ((225, 245, 235), (15, 40, 30), (30, 120, 80)),
    "F4": ((240, 225, 250), (40, 15, 60), (110, 40, 150)),
}
# Each slash separates one five-pixel row. No host fonts or locale are used.
_GLYPHS = {
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00001/01110",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "01110/00100/00100/00100/00100/00100/01110",
    "J": "00111/00010/00010/00010/10010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/10101/01010",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    " ": "00000/00000/00000/00000/00000/00000/00000",
    ".": "00000/00000/00000/00000/00000/00110/00110",
    ":": "00000/00110/00110/00000/00110/00110/00000",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    "$": "00100/01111/10100/01110/00101/11110/00100",
}
FONT = {char: tuple(tuple(int(bit) for bit in row) for row in glyph.split("/"))
        for char, glyph in _GLYPHS.items()}


def luminance(rgb):
    return sum(weight * component for weight, component in zip((299, 587, 114), rgb, strict=True)) // 1000


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def encode(pixels, width=WIDTH, height=HEIGHT):
    if len(pixels) != width * height * 3:
        raise ValueError("RGB size mismatch")
    rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b"")


def decode(png):
    """Accept only the RGB, single-IDAT, filter-zero PNG subset emitted here."""
    if not png.startswith(SIGNATURE):
        raise ValueError("PNG signature")
    offset, chunks = len(SIGNATURE), []
    while offset < len(png):
        size = struct.unpack(">I", png[offset:offset + 4])[0]
        kind = png[offset + 4:offset + 8]
        data = png[offset + 8:offset + 8 + size]
        crc = png[offset + 8 + size:offset + 12 + size]
        if len(crc) != 4 or struct.unpack(">I", crc)[0] != zlib.crc32(kind + data):
            raise ValueError("PNG CRC")
        chunks.append((kind, data))
        offset += size + 12
    if [kind for kind, data in chunks] != [b"IHDR", b"IDAT", b"IEND"] or chunks[-1][1]:
        raise ValueError("PNG chunks")
    width, height, *format_ = struct.unpack(">IIBBBBB", chunks[0][1])
    if format_ != [8, 2, 0, 0, 0] or width < 1 or height < 1:
        raise ValueError("PNG format")
    rows = zlib.decompress(chunks[1][1])
    stride = width * 3 + 1
    if len(rows) != height * stride or any(rows[y * stride] != 0 for y in range(height)):
        raise ValueError("PNG rows")
    return width, height, b"".join(rows[y * stride + 1:(y + 1) * stride] for y in range(height))


def _rectangle(pixels, bbox, colour):
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 < x1 <= WIDTH and 0 <= y0 < y1 <= HEIGHT):
        raise ValueError("element outside canvas")
    row = bytes(colour) * (x1 - x0)
    for y in range(y0, y1):
        pixels[(y * WIDTH + x0) * 3:(y * WIDTH + x1) * 3] = row


def _text(pixels, text, x, y, scale, colour):
    bbox = [x, y, x + (6 * len(text) - 1) * scale, y + 7 * scale]
    if not text or not (0 <= bbox[0] < bbox[2] <= WIDTH and 0 <= bbox[1] < bbox[3] <= HEIGHT):
        raise ValueError("text outside canvas")
    for index, char in enumerate(text):
        for gy, row in enumerate(FONT[char]):
            for gx, bit in enumerate(row):
                if bit:
                    px, py = x + (6 * index + gx) * scale, y + gy * scale
                    _rectangle(pixels, [px, py, px + scale, py + scale], colour)
    return bbox


def presentation(record, presentation_seed):
    unit = ("p08", record["life"], record["image_id"], "presentation")
    names = ("family", "scale", "margin", "jitter")
    ranges = ((0, 3), (2, 3), (16, 24), (0, 16))
    return {name: uniform_int(str(presentation_seed), unit, 0, name, *bounds)
            for name, bounds in zip(names, ranges, strict=True)}


def _rows(record):
    if record["kind"] == "settings":
        return [[field] for field in ("SERVICE", "PORT", "MODE")]
    if record["kind"] == "receipt":
        return [["STORE"], *[[f"ITEM{i}", f"PRICE{i}"] for i in range(1, 4)], ["TOTAL"]]
    if record["kind"] == "desk":
        return [[f"OBJECT{i}", f"CODE{i}"] for i in range(1, 6)]
    raise ValueError("unknown image kind")


def _polygon(pixels, points, fill, outline):
    """Integer scanline fill and Bresenham outline, independent of host graphics."""
    edges = list(zip(points, points[1:] + points[:1], strict=True))
    for y in range(min(p[1] for p in points), max(p[1] for p in points)):
        cuts = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) // (b[1] - a[1])
                      for a, b in edges if min(a[1], b[1]) <= y < max(a[1], b[1]))
        for left, right in zip(cuts[::2], cuts[1::2], strict=True):
            if right > left:
                _rectangle(pixels, [left, y, right, y + 1], fill)
    for (x, y), (end_x, end_y) in edges:
        dx, dy = abs(end_x - x), -abs(end_y - y)
        sx, sy = (1 if x < end_x else -1), (1 if y < end_y else -1)
        error = dx + dy
        while True:
            _rectangle(pixels, [x, y, x + 1, y + 1], outline)
            if (x, y) == (end_x, end_y):
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x += sx
            if twice <= dx:
                error += dx
                y += sy


def _object(pixels, obj, x, y, background, foreground, accent):
    def polygon(points, fill=accent):
        _polygon(pixels, [(x + px, y + py) for px, py in points], fill, foreground)

    if obj == "MUG":
        polygon([(48, 9), (65, 9), (70, 16), (65, 29), (48, 29)], background)
        polygon([(12, 4), (51, 4), (48, 39), (17, 39)])
    elif obj == "LAMP":
        polygon([(33, 6), (36, 6), (36, 37), (33, 37)])
        polygon([(20, 0), (49, 0), (63, 22), (7, 22)])
        polygon([(19, 37), (50, 37), (55, 41), (14, 41)])
    elif obj == "BOOK":
        polygon([(3, 3), (31, 6), (35, 10), (40, 6), (68, 3), (68, 37),
                 (40, 40), (35, 42), (31, 40), (3, 37)])
        polygon([(35, 10), (35, 41)], foreground)
    elif obj == "PLANT":
        polygon([(34, 30), (34, 4)], foreground)
        for points in ([(34, 18), (12, 1), (12, 14), (34, 24)],
                       [(34, 12), (56, 0), (52, 14), (34, 23)]):
            polygon(points)
        polygon([(18, 25), (51, 25), (46, 42), (23, 42)])
    elif obj == "PHONE":
        polygon([(21, 0), (51, 0), (51, 42), (21, 42)])
        polygon([(25, 5), (47, 5), (47, 33), (25, 33)], background)
        polygon([(32, 38), (40, 38)], foreground)
    elif obj == "CLOCK":
        polygon([(18, 0), (49, 0), (65, 15), (65, 28), (49, 42), (18, 42), (4, 28), (4, 15)])
        polygon([(35, 7), (35, 23), (49, 23)], background)
    else:
        raise ValueError("unknown desk object")


def render(record, family, presentation_seed):
    """Return PNG bytes and exposed entries, including the verifier's scale and colours.

    Bboxes are half-open. The fifth desk tag is covered by a sticky note and
    omitted. Records use string values, including cents formatted as d.dd.
    """
    background, foreground, accent = FAMILIES[family]
    contrast = abs(luminance(background) - luminance(foreground))
    if contrast < 100:
        raise ValueError("insufficient contrast")
    style = presentation(record, presentation_seed)
    scale, margin = style["scale"], style["margin"]
    rows = shuffle(str(presentation_seed), ("p08", record["life"], record["image_id"], "presentation"),
                   0, "row-order", _rows(record))
    pixels = bytearray(bytes(background) * WIDTH * HEIGHT)
    _rectangle(pixels, [0, 0, WIDTH, 6], accent)
    manifest, elements = [], []
    for index, fields in enumerate(rows):
        x, y = margin + style["jitter"], 24 + index * 55
        if record["kind"] == "desk":
            x += (index % 2) * 230
            y = 28 + (index // 2) * 92
            _object(pixels, record["values"][fields[0]], x + 20, y,
                    background, foreground, accent)
            elements.append([x + 20, y, x + 91, y + 43])
            y += 48
        label = record["kind"].upper() if index == 0 else "-"
        # The header is separate from the value bboxes and never becomes gold.
        if index == 0:
            _text(pixels, label, x, 8, 2, accent)
        entries = []
        if len(fields) == 1:
            label_box = _text(pixels, fields[0] + ":", x, y, scale, foreground)
            elements.append(label_box)
            x = label_box[2] + 12
        for field in fields:
            value = record["values"][field]
            bbox = _text(pixels, value, x, y, scale, foreground)
            elements.append(bbox)
            entries.append({"field": field, "value": value, "bbox": bbox,
                            "scale": scale, "foreground": list(foreground), "background": list(background)})
            x = bbox[2] + 18
        if record["kind"] == "desk" and "CODE5" in fields:
            bbox = entries[-1]["bbox"]
            cover = [entries[0]["bbox"][0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2]
            _rectangle(pixels, cover, accent)
            elements.append(cover)
            entries = []
        manifest.extend(entries)
    manifest = [entry for entry in manifest if all(
        other is entry["bbox"] or not intersects(entry["bbox"], other) for other in elements)]
    return encode(pixels), manifest


def crop(png, bbox, margin=0):
    width, height, pixels = decode(png)
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(width, x1 + margin), min(height, y1 + margin)
    rows = b"".join(pixels[(y * width + x0) * 3:(y * width + x1) * 3] for y in range(y0, y1))
    return encode(rows, x1 - x0, y1 - y0)


def _read(width, pixels, entry):
    x0, y0, x1, y1 = entry["bbox"]
    scale, foreground, background = entry["scale"], bytes(entry["foreground"]), bytes(entry["background"])
    if y1 - y0 != 7 * scale or (x1 - x0 + scale) % (6 * scale):
        return None
    text = ""
    for left in range(x0, x1, 6 * scale):
        matches = []
        for char, glyph in FONT.items():
            if all(pixels[((y0 + dy) * width + left + dx) * 3:
                          ((y0 + dy) * width + left + dx) * 3 + 3]
                   == (foreground if glyph[dy // scale][dx // scale] else background)
                   for dy in range(7 * scale) for dx in range(5 * scale)):
                matches.append(char)
        if len(matches) != 1:
            return None
        text += matches[0]
        # Inter-character spacing is part of the exact template too.
        if left + 6 * scale < x1 and any(
            pixels[(y * width + x) * 3:(y * width + x) * 3 + 3] != background
            for y in range(y0, y1) for x in range(left + 5 * scale, left + 6 * scale)):
            return None
    return text


def verify(png_bytes, manifest):
    width, height, pixels = decode(png_bytes)
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError("canvas size")
    matched = sum(_read(width, pixels, entry) == entry["value"] for entry in manifest)
    checked = len(manifest)
    return {"checked": checked, "matched": matched, "recall_milli": 1000 * matched // checked if checked else 0}

def keysheet(images, n=200):
    """Return sampled crops and private answer metadata; the CLI writes only blank keys."""
    candidates = [(image, entry) for image in images for entry in image["manifest"]]
    rows = []
    for index in range(n):
        selected = uniform_int("p08", ("p08", "keysheet"), 0, f"entry#{index}", 0, len(candidates) - 1)
        image, entry = candidates[selected]
        checked = verify(image["png"], [entry])
        rows.append({"id": str(index), "crop": f"crop-{index:03d}.png", "value": entry["value"],
                     "matched": checked["matched"] == 1,
                     "png": crop(image["png"], entry["bbox"], 8)})
    return rows


def fidelity(rows, key_csv):
    with Path(key_csv).open(newline="") as handle:
        key = list(csv.DictReader(handle))
    if len(key) != len(rows) or {row["id"] for row in key} != {row["id"] for row in rows}:
        raise ValueError("keysheet identity mismatch")
    typed = {row["id"]: row for row in key}
    if any(not row["typed"].strip() for row in key):
        return {"n": len(rows), "state": "pending_human_key"}
    legible = [row for row in rows if typed[row["id"]]["typed"].strip() == row["value"]]
    return {"n": len(rows), "legible_milli": 1000 * len(legible) // len(rows),
            "verifier_recall_milli": 1000 * sum(row["matched"] for row in legible) // len(legible) if legible else 0}
