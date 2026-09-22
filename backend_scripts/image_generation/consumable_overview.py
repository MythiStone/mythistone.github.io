"""Renderer for the consumable social/OG preview cards (1200x675): one per
consumable page plus the /pages/consumables browse-page overview card.

Takes no DB handle: fed the fully-assembled ``payload`` dicts (and manifest) that
``generateConsumablePages`` already builds, drawing only from those plus the
DB-free static lookups. Reuses the item-card helpers (background, spec visuals,
icon paste, panels, watermark) so the consumable cards read as the same system.

Consumables carry no item rarity, so icons use a neutral grey border rather than a
quality colour. The entity set is tiny (~40), so previews render sequentially
rather than through a multiprocessing Pool.

Entrypoints:
    render_consumable_card(payload, slug, out_path)
    render_consumable_previews(payloads, slug_map, order)
    render_consumables_overview(manifest, season_name, out_path)
"""

import os

from PIL import ImageDraw, ImageFont

from commonUtils import humanize_number
from image_generation import config
from image_generation.pil_helpers import (
    apply_watermark_to_canvas,
    draw_panel,
    fit_font_to_width,
)
from image_generation.item_overview import (
    _ensure_lookups,
    _get_background,
    _paste_icon,
    _spec_visual,
)

# og:image for the /pages/consumables browse page. A sibling of the per-consumable
# previews dir so it can never collide with a consumable's <slug>.jpg card.
OVERVIEW_REL_PATH = os.path.join("assets", "img", "previews", "consumables_overview.jpg")
OVERVIEW_URL = "https://mythistone.com/assets/img/previews/consumables_overview.jpg"
OVERVIEW_TOP_N = 15

PREVIEWS_DIR = os.path.join("assets", "img", "previews", "consumables")

# Neutral grey icon border (consumables have no rarity colour).
ICON_BORDER = (110, 116, 130)


def _save(canvas, out_path):
    canvas = canvas.convert("RGB")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if out_path.lower().endswith((".jpg", ".jpeg")):
        canvas.save(out_path, quality=82, optimize=True)
    else:
        canvas.save(out_path)
    return out_path


def render_consumable_card(payload, slug, out_path):
    """Render one consumable's preview card to ``out_path`` (``.jpg`` -> JPEG)."""
    _ensure_lookups()
    W, H = config.WIDTH, config.HEIGHT

    canvas = _get_background().convert("RGB")
    draw = ImageDraw.Draw(canvas)

    font_sub = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE)
    font_panel_title = ImageFont.truetype(config.FONT_FILE, config.SUBTITLE_SIZE)
    font_row = ImageFont.truetype(config.FONT_FILE, max(20, config.SMALL_SIZE))

    margin = 40
    # ---- header: icon + name, then category + runs strip stacked beneath ----
    icon_sz = 96
    icon_top = 30
    icon_path = os.path.join(config.ICON_DIR, f"{payload.get('icon', '')}.png")
    name_x = margin
    if _paste_icon(canvas, icon_path, (margin, icon_top), icon_sz):
        draw.rectangle((margin, icon_top, margin + icon_sz, icon_top + icon_sz),
                       outline=ICON_BORDER, width=2)
        name_x = margin + icon_sz + 20

    name = payload.get("name", f"Item {payload.get('id', '')}")
    max_title_w = W - name_x - margin
    title_font = fit_font_to_width(draw, name, max_title_w,
                                   start_size=config.TITLE_SIZE, min_size=20, step=2)
    name_y = 32
    draw.text((name_x, name_y), name, font=title_font, fill=config.TEXT)

    sub_y = name_y + title_font.size + 4
    draw.text((name_x, sub_y), (payload.get("category_label") or "").upper(),
              font=font_sub, fill=config.MUTED)

    strip = f"{humanize_number(payload.get('total_runs', 0))} RUNS".strip()
    if payload.get("category_share") is not None:
        strip += f"   •   {payload['category_share']}% OF {(payload.get('category_label') or '').upper()}"
    strip_y = sub_y + font_sub.size + 10
    draw.text((name_x, strip_y), strip, font=font_sub, fill=config.TEXT)

    divider_y = max(strip_y + font_sub.size + 14, icon_top + icon_sz + 14)
    draw.line([(margin, divider_y), (W - margin, divider_y)], fill=config.DIVIDER, width=2)

    # ---- "Used by" panel: top specs by tracked usage ----
    x0, y0, x1, y1 = margin, divider_y + 16, W - margin, H - 56
    draw_panel(draw, [(x0, y0), (x1, y1)], radius=12)
    pad = 16
    draw.text((x0 + pad, y0 + pad), "Used by", font=font_panel_title, fill=config.TEXT)
    ry = y0 + pad + font_panel_title.size + 10
    icon_sz2 = 30
    row_h = icon_sz2 + 12
    max_rows = max(0, int((y1 - pad - ry) // row_h))
    for s in (payload.get("specs") or [])[:max_rows]:
        nm, cc, spec_icon = _spec_visual(s["spec_id"])
        cy = ry + icon_sz2 // 2
        text_x = x0 + pad
        if _paste_icon(canvas, spec_icon, (x0 + pad, ry), icon_sz2):
            draw.rectangle((x0 + pad, ry, x0 + pad + icon_sz2, ry + icon_sz2),
                           outline=cc, width=2)
            text_x = x0 + pad + icon_sz2 + 12
        # share % (right-aligned)
        val_right = x1 - pad
        if s.get("share") is not None:
            val = f"{s['share']}%"
            vw = draw.textlength(val, font=font_row)
            draw.text((val_right - vw, cy), val, font=font_row, fill=config.MUTED, anchor="lm")
            val_right = val_right - vw - 10
        label = nm
        max_w = val_right - text_x
        while label and draw.textlength(label, font=font_row) > max_w and len(label) > 1:
            label = label[:-1]
        if label != nm and label:
            label = label[:-1] + "…"
        draw.text((text_x, cy), label, font=font_row, fill=cc, anchor="lm")
        ry += row_h

    canvas = apply_watermark_to_canvas(canvas, position="bottom_right",
                                       padding_x=30, padding_y=10)
    return _save(canvas, out_path)


def render_consumable_previews(payloads, slug_map, order, previews_dir=PREVIEWS_DIR):
    """Render one preview card per consumable, sequentially. ``order`` is the
    manifest (runs desc); ``payloads`` is keyed by item id."""
    os.makedirs(previews_dir, exist_ok=True)
    done = failed = 0
    for m in order:
        pl = payloads.get(m["id"])
        if not pl:
            continue
        slug = slug_map[m["id"]]
        try:
            render_consumable_card(pl, slug, os.path.join(previews_dir, f"{slug}.jpg"))
            done += 1
        except Exception as e:  # one bad card must not kill the batch
            failed += 1
            print(f"  consumable preview FAIL {slug}: {e!r}")
    print(f"wrote {done} consumable preview cards to {previews_dir}/ ({failed} failed)")
    return done


def render_consumables_overview(manifest, season_name, out_path, top_n=OVERVIEW_TOP_N):
    """Render the /pages/consumables browse OG card: a grid of the most-used
    consumables this season. Each cell is [rank] [icon] [name] [top-spec] [runs]."""
    _ensure_lookups()
    W, H = config.WIDTH, config.HEIGHT
    margin = 40

    canvas = _get_background().convert("RGB")
    draw = ImageDraw.Draw(canvas)

    font_sub = ImageFont.truetype(config.FONT_FILE, config.SMALL_SIZE)
    font_row = ImageFont.truetype(config.FONT_FILE, max(20, config.SMALL_SIZE))
    font_rank = ImageFont.truetype(config.FONT_FILE, max(18, config.SMALL_SIZE - 2))

    title = "Mythic+ Consumable Usage"
    title_font = fit_font_to_width(draw, title, W - 2 * margin,
                                   start_size=config.TITLE_SIZE, min_size=24, step=2)
    title_y = 30
    draw.text((margin, title_y), title, font=title_font, fill=config.TEXT)
    sub_bits = [season_name or "", f"{len(manifest):,} consumables tracked"]
    subtitle = "  •  ".join(b for b in sub_bits if b)
    sub_y = title_y + title_font.size + 6
    draw.text((margin, sub_y), subtitle.upper(), font=font_sub, fill=config.MUTED)
    divider_y = sub_y + font_sub.size + 14
    draw.line([(margin, divider_y), (W - margin, divider_y)], fill=config.DIVIDER, width=2)

    entries = manifest[:top_n]
    cols, rows = 3, 5
    col_gap, row_gap = 20, 12
    top = divider_y + 16
    bottom = H - 56
    cell_w = (W - 2 * margin - (cols - 1) * col_gap) / cols
    cell_h = (bottom - top - (rows - 1) * row_gap) / rows
    icon_sz = int(min(cell_h - 8, 54))
    pad = 10

    for idx, m in enumerate(entries):
        c, r = idx % cols, idx // cols
        x0 = margin + c * (cell_w + col_gap)
        y0 = top + r * (cell_h + row_gap)
        x1 = x0 + cell_w
        cy = y0 + cell_h / 2
        draw_panel(draw, [(int(x0), int(y0)), (int(x1), int(y0 + cell_h))], radius=10)

        rank = str(idx + 1)
        draw.text((x0 + pad, cy), rank, font=font_rank, fill=config.MUTED, anchor="lm")
        ix = x0 + pad + draw.textlength(rank, font=font_rank) + 8

        icon_path = os.path.join(config.ICON_DIR, f"{m.get('icon', '')}.png")
        iy = cy - icon_sz / 2
        if _paste_icon(canvas, icon_path, (int(ix), int(iy)), icon_sz):
            draw.rectangle((int(ix), int(iy), int(ix + icon_sz), int(iy + icon_sz)),
                           outline=ICON_BORDER, width=2)
            text_x = ix + icon_sz + 10
        else:
            text_x = ix

        runs = humanize_number(m.get("runs", 0))
        val_right = x1 - pad
        rw = draw.textlength(runs, font=font_row)
        draw.text((val_right - rw, cy), runs, font=font_row, fill=config.MUTED, anchor="lm")
        val_right = val_right - rw - 10

        if m.get("top_spec") is not None:
            _nm, cc, spec_icon = _spec_visual(m["top_spec"])
            sp_sz = 26
            sx = val_right - sp_sz
            sy = cy - sp_sz / 2
            if _paste_icon(canvas, spec_icon, (int(sx), int(sy)), sp_sz):
                draw.rectangle((int(sx), int(sy), int(sx + sp_sz), int(sy + sp_sz)),
                               outline=cc, width=2)
                val_right = sx - 10

        name = m.get("name", f"Item {m.get('id', '')}")
        max_w = val_right - text_x
        label = name
        while label and draw.textlength(label, font=font_row) > max_w and len(label) > 1:
            label = label[:-1]
        if label != name and label:
            label = label[:-1] + "…"
        draw.text((text_x, cy), label, font=font_row, fill=config.TEXT, anchor="lm")

    canvas = apply_watermark_to_canvas(canvas, position="bottom_right",
                                       padding_x=30, padding_y=10)
    return _save(canvas, out_path)
