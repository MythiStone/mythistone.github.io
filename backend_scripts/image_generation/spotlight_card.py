"""Single-subject spotlight card: a big spec/dungeon icon on the left and a few
stat rows on the right, either "label: value" or "label: old -> new". Used by
the weekly-mover and underdog-spotlight social posts. Pure PIL, no DB."""

import os

from PIL import Image, ImageDraw, ImageFont

from image_generation import config
from image_generation.pil_helpers import (
    LANCZOS,
    apply_watermark_to_canvas,
    cover_crop,
    draw_header,
    draw_panel,
    random_background_canvas,
    rounded_alpha,
)

UP_RGB = (82, 215, 105)
DOWN_RGB = (255, 123, 123)
ICON_SIZE = 300


def _arrow(draw, x, cy, size, fill):
    """Right-pointing arrow drawn as shapes (Bebas Neue has no arrow glyph)."""
    shaft = size * 0.55
    draw.rectangle([x, cy - size * 0.09, x + shaft, cy + size * 0.09], fill=fill)
    draw.polygon([(x + shaft - 2, cy - size * 0.3), (x + size, cy), (x + shaft - 2, cy + size * 0.3)], fill=fill)
    return x + size


def render_spotlight_card(out_path, title, subtitle, icon_path, rows, accent=None):
    """rows: [(label, value)] or [(label, old, new)]; ``accent`` colours the new value
    ("up" green, "down" red, None plain)."""
    width, height = config.WIDTH, config.HEIGHT
    canvas = random_background_canvas(width, height, alpha=config.BG_ALPHA, base=config.BG)
    draw = ImageDraw.Draw(canvas, "RGBA")
    top = draw_header(draw, title, subtitle, width, margin=56)

    margin = 56
    icon_y = top + (height - top - ICON_SIZE) // 2 - 10
    if icon_path and os.path.exists(icon_path):
        icon = cover_crop(Image.open(icon_path).convert("RGBA"), ICON_SIZE, ICON_SIZE)
        icon = rounded_alpha(icon.resize((ICON_SIZE, ICON_SIZE), LANCZOS), 24)
        canvas.paste(icon, (margin, icon_y), icon)

    panel_x = margin + ICON_SIZE + 48
    panel_box = (panel_x, top + 10, width - margin, height - 60)
    draw_panel(draw, panel_box, radius=16)

    label_font = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE)
    value_font = ImageFont.truetype(config.FONT_FILE, int(height * 0.085))
    accent_rgb = {"up": UP_RGB, "down": DOWN_RGB}.get(accent, config.TEXT)

    label_h = draw.textbbox((0, 0), "A", font=label_font, anchor="lt")[3]
    value_h = draw.textbbox((0, 0), "0", font=value_font, anchor="lt")[3]
    block_h = label_h + 10 + value_h
    row_h = (panel_box[3] - panel_box[1]) / max(len(rows), 1)
    for i, row in enumerate(rows):
        top_y = panel_box[1] + row_h * i + (row_h - block_h) / 2
        x = panel_x + 32
        draw.text((x, top_y), str(row[0]).upper(), font=label_font, fill=config.MUTED, anchor="lt")
        vy = top_y + label_h + 10
        if len(row) == 3:
            old, new = str(row[1]), str(row[2])
            draw.text((x, vy), old, font=value_font, fill=config.MUTED, anchor="lt")
            ax = x + draw.textlength(old, font=value_font) + 24
            ax = _arrow(draw, ax, vy + value_h / 2, 44, accent_rgb) + 24
            draw.text((ax, vy), new, font=value_font, fill=accent_rgb, anchor="lt")
        else:
            draw.text((x, vy), str(row[1]), font=value_font, fill=config.TEXT, anchor="lt")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    canvas = apply_watermark_to_canvas(canvas, position="bottom_right", padding_x=30, padding_y=20)
    canvas.save(out_path)
