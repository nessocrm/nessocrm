"""Riscrive assets/logo a partire dal marchio usato nel menu. Vedi docs/14-marchio.md."""
from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw
from svg.path import parse_path

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = ROOT / "motore" / "fonts" / "Inter-SemiBold.woff2"
OUT = ROOT / "assets" / "logo"
LONG = 4096

SLATE = "#8B939C"
AMBER = "#E4A133"
BLUE = "#5589CA"
GREEN = "#58C97A"
INK = "#262626"
WORD = "#8090A0"
PAPER = "#F4F5F7"
WHITE = "#FEFEFE"

font = TTFont(FONT_PATH)
glyphs = font.getGlyphSet()
cmap = font.getBestCmap()
UPEM = font["head"].unitsPerEm
ASC = font["hhea"].ascender
DESC = font["hhea"].descender


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def mark_squares(x: float, y: float, size: float) -> list[dict]:
    unit = size / 26
    square = 11 * unit
    gap = 2 * unit
    radius = 2 * unit
    x0 = x
    y0 = y
    x1 = x + square + gap
    y1 = y + square + gap
    colors = (SLATE, AMBER, BLUE, GREEN)
    spots = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
    return [
        {"kind": "round", "box": (x, y, x + square, y + square), "radius": radius, "fill": color}
        for (x, y), color in zip(spots, colors)
    ]


def recolor(squares: list[dict], fill: str) -> list[dict]:
    return [{**item, "fill": fill} for item in squares]


def text_shapes(text: str, x: float, baseline: float, font_size: float, fill: str) -> tuple[list[dict], float]:
    scale = font_size / UPEM
    spacing = -0.03 * font_size
    cursor = x
    shapes = []
    for char in text:
        glyph = glyphs[cmap[ord(char)]]
        pen = SVGPathPen(glyphs)
        glyph.draw(pen)
        commands = pen.getCommands()
        if commands:
            shapes.append({
                "kind": "glyph",
                "d": commands,
                "x": cursor,
                "baseline": baseline,
                "scale": scale,
                "fill": fill,
            })
        cursor += glyph.width * scale + spacing
    width = cursor - x - spacing
    return shapes, width


def word_block(mark: float, font_ratio: float = 22 / 26) -> tuple[float, float, float]:
    font_size = mark * font_ratio
    em_top = (mark - font_size) / 2
    baseline = em_top + ASC / UPEM * font_size
    return font_size, baseline, em_top


def scene_for(kind: str, word: str = WORD) -> tuple[list[dict], float, float]:
    mark = 1040.0
    shapes: list[dict] = []
    if kind == "marchio":
        shapes.extend(mark_squares(0, 0, mark))
        return shapes, mark, mark
    if kind == "marchio-mono":
        shapes.extend(recolor(mark_squares(0, 0, mark), INK))
        return shapes, mark, mark
    if kind == "marchio-negativo":
        shapes.extend(recolor(mark_squares(0, 0, mark), WHITE))
        return shapes, mark, mark
    if kind == "wordmark":
        font_size = 880.0
        baseline = ASC / UPEM * font_size
        glyphs_shapes, width = text_shapes("Nesso", 0, baseline, font_size, WORD)
        height = (ASC - DESC) / UPEM * font_size
        return glyphs_shapes, width, height
    if kind == "wordmark-su-scuro":
        font_size = 880.0
        baseline = ASC / UPEM * font_size
        glyphs_shapes, width = text_shapes("Nesso", 0, baseline, font_size, PAPER)
        height = (ASC - DESC) / UPEM * font_size
        return glyphs_shapes, width, height
    font_size, baseline, _ = word_block(mark)
    gap = mark * (8 / 26)
    if kind == "lockup":
        shapes.extend(mark_squares(0, 0, mark))
        glyphs_shapes, width = text_shapes("Nesso", mark + gap, baseline, font_size, word)
        shapes.extend(glyphs_shapes)
        return shapes, mark + gap + width, mark
    if kind == "lockup-verticale":
        glyphs_shapes, width = text_shapes("Nesso", 0, 0, font_size, word)
        stack_gap = mark * 0.22
        text_height = (ASC - DESC) / UPEM * font_size
        total_w = max(mark, width)
        shapes.extend(mark_squares((total_w - mark) / 2, 0, mark))
        shift = (total_w - width) / 2
        moved = []
        for item in glyphs_shapes:
            moved.append({**item, "x": item["x"] + shift, "baseline": mark + stack_gap + ASC / UPEM * font_size})
        shapes.extend(moved)
        return shapes, total_w, mark + stack_gap + text_height
    raise KeyError(kind)


GROUNDS = {
    "su-chiaro": PAPER,
    "su-scuro": INK,
}


def with_ground(kind: str, ground_name: str) -> tuple[list[dict], float, float, str]:
    base = kind.removesuffix("-su-chiaro").removesuffix("-su-scuro")
    if base == "wordmark" and ground_name == "su-scuro":
        base = "wordmark-su-scuro"
    ink = PAPER if ground_name == "su-scuro" and base in ("lockup", "lockup-verticale") else WORD
    shapes, width, height = scene_for(base, ink)
    pad = max(width, height) * 0.16
    moved = []
    for item in shapes:
        if item["kind"] == "round":
            x0, y0, x1, y1 = item["box"]
            moved.append({**item, "box": (x0 + pad, y0 + pad, x1 + pad, y1 + pad)})
        else:
            moved.append({**item, "x": item["x"] + pad, "baseline": item["baseline"] + pad})
    return moved, width + pad * 2, height + pad * 2, GROUNDS[ground_name]


def svg_text(shapes: list[dict], width: float, height: float, ground: str | None) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.3f} {height:.3f}" role="img" aria-label="Nesso">',
    ]
    if ground:
        parts.append(f'<rect width="100%" height="100%" fill="{ground}"/>')
    for item in shapes:
        if item["kind"] == "round":
            x0, y0, x1, y1 = item["box"]
            parts.append(
                f'<rect x="{x0:.3f}" y="{y0:.3f}" width="{x1 - x0:.3f}" height="{y1 - y0:.3f}" rx="{item["radius"]:.3f}" fill="{item["fill"]}"/>'
            )
        else:
            parts.append(
                f'<path d="{item["d"]}" fill="{item["fill"]}" transform="translate({item["x"]:.3f} {item["baseline"]:.3f}) scale({item["scale"]:.6f} {-item["scale"]:.6f})"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def raster(shapes: list[dict], width: float, height: float, ground: str | None) -> Image.Image:
    scale = LONG / max(width, height)
    px_w = max(1, round(width * scale))
    px_h = max(1, round(height * scale))
    image = Image.new("RGBA", (px_w, px_h), (0, 0, 0, 0))
    if ground:
        plate = Image.new("RGBA", (px_w, px_h), (*hex_rgb(ground), 255))
        image.alpha_composite(plate)
    draw = ImageDraw.Draw(image)
    for item in shapes:
        if item["kind"] != "round":
            continue
        x0, y0, x1, y1 = item["box"]
        box = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
        draw.rounded_rectangle(box, radius=item["radius"] * scale, fill=(*hex_rgb(item["fill"]), 255))
    for item in shapes:
        if item["kind"] != "glyph":
            continue
        path = parse_path(item["d"])
        subpaths: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for segment in path:
            start = segment.start
            if not current or abs(current[-1][0] - start.real) > 0.01 or abs(current[-1][1] - start.imag) > 0.01:
                if len(current) > 2:
                    subpaths.append(current)
                current = [(start.real, start.imag)]
            steps = 48
            for step in range(1, steps + 1):
                point = segment.point(step / steps)
                current.append((point.real, point.imag))
        if len(current) > 2:
            subpaths.append(current)
        mask = Image.new("L", (px_w, px_h), 0)
        for sub in subpaths:
            layer = Image.new("L", (px_w, px_h), 0)
            layer_draw = ImageDraw.Draw(layer)
            points = [
                ((item["x"] + px * item["scale"]) * scale, (item["baseline"] - py * item["scale"]) * scale)
                for px, py in sub
            ]
            layer_draw.polygon(points, fill=255)
            mask = ImageChops.difference(mask, layer)
        color = Image.new("RGBA", (px_w, px_h), (*hex_rgb(item["fill"]), 255))
        image.paste(color, (0, 0), mask)
    return image


def write_set(name: str, shapes: list[dict], width: float, height: float, ground: str | None, jpg_ground: str) -> None:
    (OUT / f"{name}.svg").write_text(svg_text(shapes, width, height, ground), encoding="utf-8")
    image = raster(shapes, width, height, ground)
    image.save(OUT / f"{name}.png", "PNG", optimize=True)
    flat = Image.new("RGB", image.size, hex_rgb(jpg_ground))
    flat.paste(image, mask=image.getchannel("A"))
    flat.save(OUT / f"{name}.jpg", "JPEG", quality=95, subsampling=0, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transparent = (
        "marchio",
        "marchio-mono",
        "marchio-negativo",
        "lockup",
        "lockup-verticale",
        "wordmark",
    )
    for name in transparent:
        shapes, width, height = scene_for(name)
        write_set(name, shapes, width, height, None, INK if name == "marchio-negativo" else PAPER)
    for base in ("marchio", "lockup", "lockup-verticale", "wordmark"):
        for ground_name in ("su-chiaro", "su-scuro"):
            if base == "wordmark" and ground_name == "su-chiaro":
                shapes, width, height = scene_for("wordmark")
                pad = max(width, height) * 0.16
                moved = [{**item, "x": item["x"] + pad, "baseline": item["baseline"] + pad} for item in shapes]
                write_set(f"{base}-{ground_name}", moved, width + pad * 2, height + pad * 2, PAPER, PAPER)
                continue
            shapes, width, height, ground = with_ground(base, ground_name)
            write_set(f"{base}-{ground_name}", shapes, width, height, ground, ground)
    manual = ROOT / "docs" / "img"
    manual.mkdir(parents=True, exist_ok=True)
    for name in ("marchio.svg", "lockup-su-chiaro.svg"):
        (manual / name).write_bytes((OUT / name).read_bytes())
    print("scritti", len(list(OUT.iterdir())), "file in", OUT)


if __name__ == "__main__":
    main()
