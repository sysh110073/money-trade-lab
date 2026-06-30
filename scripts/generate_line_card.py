from __future__ import annotations

import random
from pathlib import Path

import pandas as pd
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


WIDTH = 1080
HEIGHT = 1920
MARGIN = 64
FONT_REGULAR = Path(r"C:\Windows\Fonts\msjh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msjhbd.ttc")

# Donut Nyan Theme
BG = "#FCE8B2"           # Pastel donut yellow/cream background
PANEL = (255, 255, 255, 180)      # White panels with partial opacity
PANEL_ALT = (255, 255, 255, 140)  # Slightly more transparent white
TEXT = "#FFFFFF"         # Main text is white
MUTED = "#8B5A2B"        # Muted text is brown
GREEN = "#4CAF50"
RED = "#E53935"
CYAN = "#FF8C00"
YELLOW = "#E65100"
LINE = "#D2B48C"         # Light brown/tan for borders
STROKE = "#704214"       # Dark brown stroke for white text

def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)

def rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int, int] | str = PANEL) -> None:
    draw.rounded_rectangle(box, radius=26, fill=fill, outline=LINE, width=2)

def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    color: str = TEXT,
    bold: bool = False,
    anchor: str | None = None,
    use_stroke: bool = True
) -> None:
    try:
        from pilmoji import Pilmoji
        with Pilmoji(draw._image) as pilmoji:
            pilmoji.text(xy, value, font=font(size, bold), fill=color, anchor=anchor, stroke_width=2 if use_stroke else 0, stroke_fill=STROKE if use_stroke else None)
    except ImportError:
        draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor, stroke_width=2 if use_stroke else 0, stroke_fill=STROKE if use_stroke else None)

def text_plain(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    color: str = "#704214",
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    try:
        from pilmoji import Pilmoji
        with Pilmoji(draw._image) as pilmoji:
            pilmoji.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)
    except ImportError:
        draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)

def net_label(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    absolute = abs(value)
    return f"{sign}{absolute / 10000:.1f}萬張" if absolute >= 10000 else f"{sign}{absolute:,.0f}張"

def load_and_rembg_image(image_path: Path, max_size: tuple[int, int]) -> Image.Image | None:
    if not image_path.exists():
        return None
    try:
        import rembg
        with Image.open(image_path) as img:
            img = rembg.remove(img)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return img
    except Exception as e:
        print(f"Failed to process {image_path}: {e}")
        return None


def _fill_alpha_holes(img: Image.Image) -> Image.Image:
    alpha = img.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > 8 else 0)
    inv = ImageOps.invert(mask)
    flood = Image.new("L", (img.width + 2, img.height + 2), 0)
    flood.paste(inv, (1, 1))
    ImageDraw.floodfill(flood, (0, 0), 255)
    outside = flood.crop((1, 1, img.width + 1, img.height + 1)).point(lambda p: 255 if p == 255 else 0)
    holes = ImageChops.subtract(inv, outside)
    fixed_alpha = ImageChops.lighter(alpha, holes)
    out = img.copy()
    out.putalpha(fixed_alpha)
    return out


def _rounded_original_sticker(img: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    out = ImageOps.exif_transpose(img).convert("RGBA")
    out.thumbnail(max_size, Image.Resampling.LANCZOS)
    mask = Image.new("L", out.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, out.width, out.height), radius=28, fill=255)
    out.putalpha(mask)
    return out


def load_cat_sticker(image_path: Path, max_size: tuple[int, int]) -> Image.Image | None:
    if not image_path.exists():
        return None
    with Image.open(image_path) as original:
        original = ImageOps.exif_transpose(original).convert("RGBA")
        try:
            import rembg

            try:
                cat = rembg.remove(
                    original,
                    alpha_matting=True,
                    alpha_matting_foreground_threshold=240,
                    alpha_matting_background_threshold=10,
                    alpha_matting_erode_size=0,
                ).convert("RGBA")
            except TypeError:
                cat = rembg.remove(original).convert("RGBA")

            cat = _fill_alpha_holes(cat)
            bbox = cat.getchannel("A").getbbox()
            if not bbox:
                return _rounded_original_sticker(original, max_size)
            cat = cat.crop(bbox)
            visible = cat.getchannel("A").point(lambda p: 1 if p > 8 else 0)
            visible_ratio = sum(visible.getdata()) / max(1, cat.width * cat.height)
            if visible_ratio < 0.35:
                return _rounded_original_sticker(original, max_size)
            cat.thumbnail(max_size, Image.Resampling.LANCZOS)
            return cat
        except Exception as e:
            print(f"Failed to process cat image {image_path}: {e}")
            return _rounded_original_sticker(original, max_size)

def create_daily_card(
    positions: pd.DataFrame,
    fund_radar: dict[str, list[dict]],
    strong_signals: list[dict],
    output_path: Path,
    action_plan: dict | None = None,
    real_portfolio: list[dict] | None = None,
) -> Path:
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    as_of = (
        str(positions["as_of_date"].iloc[0])[:10]
        if not positions.empty
        else str((action_plan or {}).get("as_of") or "最新交易日")[:10]
    )

    # Background Decorations
    artifacts_dir = Path(r"C:\Users\huang\.gemini\antigravity\brain\9da0552b-16f1-467d-821e-1094ff40a7fb")
    fish_img = load_and_rembg_image(list(artifacts_dir.glob("q_fish*.png"))[0] if list(artifacts_dir.glob("q_fish*.png")) else Path("nonexistent"), (180, 180))
    wand_img = load_and_rembg_image(list(artifacts_dir.glob("q_wand*.png"))[0] if list(artifacts_dir.glob("q_wand*.png")) else Path("nonexistent"), (200, 200))
    
    if fish_img:
        image.alpha_composite(fish_img.rotate(15, expand=True), dest=(30, 200))
        image.alpha_composite(fish_img.rotate(-20, expand=True), dest=(850, 1000))
    if wand_img:
        image.alpha_composite(wand_img.rotate(-10, expand=True), dest=(880, 250))
        image.alpha_composite(wand_img.rotate(25, expand=True), dest=(20, 1100))

    # Header
    text(draw, (MARGIN, 70), "本喵每日選股與指引", 58, bold=True)
    text_plain(draw, (WIDTH - MARGIN, 92), as_of, 28, MUTED, anchor="ra")
    text_plain(draw, (MARGIN, 145), "實盤操作 × 策略選股 × 法人資金", 26, STROKE)

    # Action Guide (Y: 205 - 650) - Split into two columns
    # Left: Strategy Holdings, Right: Real Portfolio
    rounded_panel(draw, (MARGIN, 205, WIDTH // 2 - 10, 650))
    rounded_panel(draw, (WIDTH // 2 + 10, 205, WIDTH - MARGIN, 650))
    
    text(draw, (MARGIN + 20, 230), "🐱 策略持股指引", 32, bold=True)
    text(draw, (WIDTH // 2 + 30, 230), "🐾 真實持股防守點", 32, bold=True)
    
    buy_now = action_plan.get("buy_now", []) if action_plan else []
    sell_now = action_plan.get("sell_now", []) if action_plan else []
    open_pos = action_plan.get("open_positions", []) if action_plan else []
    
    y_left = 290
    if sell_now:
        text_plain(draw, (MARGIN + 20, y_left), "【汰換賣出】", 24, RED, bold=True)
        y_left += 35
        for s in sell_now[:2]:
            suffix = f"換入 {s.get('replacedBy')}" if s.get("replacedBy") else "賣出"
            text_plain(draw, (MARGIN + 30, y_left), f"• {s.get('symbol')} {s.get('name')} ({suffix})", 22, STROKE, bold=True)
            y_left += 35
        y_left += 10

    if buy_now:
        text_plain(draw, (MARGIN + 20, y_left), "【建議買入】", 24, YELLOW, bold=True)
        y_left += 35
        for b in buy_now[:2]:
            text_plain(draw, (MARGIN + 30, y_left), f"• {b.get('symbol')} {b.get('name')} ({b.get('shares')}股)", 22, STROKE, bold=True)
            y_left += 35
        y_left += 10
    
    if open_pos:
        text_plain(draw, (MARGIN + 20, y_left), "【策略防守點】", 24, YELLOW, bold=True)
        y_left += 35
        for p in open_pos[:8]:
            if y_left > 615:
                break
            stop_loss = float(p.get('stopLoss', 0))
            trailing_stop = float(p.get('trailingStop', 0))
            is_trailing = trailing_stop > stop_loss
            stop_type = "移動止盈" if is_trailing else "初始停損"
            stop_price = trailing_stop if is_trailing else stop_loss
            risk_label = str(p.get("riskControlLabel") or "")
            label = f"• {p.get('symbol')} {p.get('name')} | {stop_price:.1f} ({stop_type})"
            if risk_label:
                label += " | 風控"
            text_plain(draw, (MARGIN + 30, y_left), label, 22, RED if risk_label else STROKE, bold=True)
            y_left += 35

    y_right = 290
    if real_portfolio:
        for p in real_portfolio[:5]:
            symbol = p.get('symbol')
            name = p.get('name', '')
            cost = p.get('buy_price', 0)
            market = p.get('current_price', 0)
            roi = p.get('roi', 0)
            profit = roi * 100
            
            stop_val = p.get('stop_price')
            stop_type = "移動止盈" if p.get('is_trailing') else "初始停損"
            
            text_plain(draw, (WIDTH // 2 + 30, y_right), f"• {symbol} {name}", 24, STROKE, bold=True)
            text_plain(draw, (WIDTH - MARGIN - 20, y_right), f"{profit:+.1f}%", 24, GREEN if profit >= 0 else RED, bold=True, anchor="ra")
            
            detail_str = f"現價 {market} (成本 {cost})"
            text_plain(draw, (WIDTH // 2 + 45, y_right + 35), detail_str, 20, MUTED)
            if stop_val:
                text_plain(draw, (WIDTH // 2 + 45, y_right + 60), f"破 {stop_val:.1f} 賣出 ({stop_type})", 20, RED)
            y_right += 95
    else:
        text_plain(draw, (WIDTH // 2 + 30, y_right), "目前無真實持股紀錄", 22, MUTED)

    # Strategy holdings (Y: 680 - 1090)
    rounded_panel(draw, (MARGIN, 680, WIDTH - MARGIN, 1090))
    text(draw, (MARGIN + 34, 713), "策略持股候補名單", 36, bold=True)
    text_plain(draw, (WIDTH - MARGIN - 34, 723), "依策略分數由高到低", 23, MUTED, anchor="ra")
    ordered = positions.sort_values(["strategy_score", "symbol"], ascending=[False, True])
    if ordered.empty:
        reason = (action_plan or {}).get("market_filter_reason") or "目前無候選名單。"
        text_plain(draw, (MARGIN + 42, 800), "目前無候選名單", 31, RED, bold=True)
        y_reason = 850
        for part in str(reason).replace("。", "。\n").replace("；", "；\n").splitlines()[:5]:
            text_plain(draw, (MARGIN + 42, y_reason), part, 24, STROKE)
            y_reason += 40
    for index, row in enumerate(ordered.itertuples(index=False)):
        column = index // 4
        row_index = index % 4
        x = MARGIN + 42 + column * 475
        y_pos = 791 + row_index * 67
        text(draw, (x, y_pos), f"{index + 1:02d}", 22, TEXT, bold=True)
        text_plain(draw, (x + 52, y_pos - 4), str(row.symbol).zfill(4), 31, STROKE, bold=True)
        text_plain(draw, (x + 155, y_pos), str(getattr(row, "name", "")), 25, STROKE)
        text_plain(draw, (x + 405, y_pos + 2), f"{float(row.strategy_score) * 100:.1f}", 22, MUTED, anchor="ra")

    # Institutional flow (Y: 1120 - 1800)
    text(draw, (MARGIN, 1150), "法人資金雷達", 40, bold=True)
    text_plain(draw, (WIDTH - MARGIN, 1162), "近 5 日淨買賣超", 23, MUTED, anchor="ra")
    columns = [
        ("資金流入 Top 3", fund_radar.get("inflow_details", []), GREEN, True),
        ("資金流出 Top 3", fund_radar.get("outflow_details", []), RED, False),
    ]
    for column_index, (title, sectors, color, inflow) in enumerate(columns):
        left = MARGIN + column_index * 492
        right = left + 460
        rounded_panel(draw, (left, 1212, right, 1800), PANEL_ALT)
        text(draw, (left + 28, 1244), title, 31, color, bold=True, use_stroke=False)
        y_pos = 1310
        for rank, sector in enumerate(sectors, start=1):
            text_plain(draw, (left + 28, y_pos), f"{rank}. {sector.get('name', '')}", 27, STROKE, bold=True)
            text_plain(
                draw,
                (right - 28, y_pos + 3),
                net_label(float(sector.get("net5") or 0)),
                21,
                color,
                anchor="ra",
            )
            y_pos += 42
            for stock in sector.get("leaders", [])[:3]:
                symbol = str(stock.get("symbol", "")).zfill(4)
                name = str(stock.get("name", ""))
                value = net_label(float(stock.get("net5") or 0))
                text_plain(draw, (left + 48, y_pos), f"{symbol} {name}", 21, MUTED)
                text_plain(draw, (right - 28, y_pos), value, 19, color, anchor="ra")
                y_pos += 34
            if rank < len(sectors):
                draw.line((left + 28, y_pos + 5, right - 28, y_pos + 5), fill=LINE, width=1)
                y_pos += 25

    text_plain(draw, (WIDTH // 2, 1870), "僅供策略追蹤，不構成投資建議", 21, MUTED, anchor="ma")

    # Cat Stickers on TOP of everything else
    cat_dir = Path(r"C:\Users\huang\Desktop\money_trade\cat_picture")
    if cat_dir.exists() and cat_dir.is_dir():
        cat_images = list(cat_dir.glob("*.jpg")) + list(cat_dir.glob("*.png"))
        if cat_images:
            try:
                cats_to_pick = random.sample(cat_images, min(2, len(cat_images)))
                cat_path_1 = cats_to_pick[0]
                cat_path_2 = cats_to_pick[1] if len(cats_to_pick) > 1 else cats_to_pick[0]

                # First Cat (Top Header Box W: 220, H: 130, Center X: 710, Y: 95)
                cat_img = load_cat_sticker(cat_path_1, (270, 145))
                if cat_img:
                    paste_x = 755 - cat_img.width // 2
                    paste_y = 75 - cat_img.height // 2
                    image.alpha_composite(cat_img, dest=(paste_x, paste_y))

                # Second Cat: 1.5x bigger and moved away from the fund-flow heading text.
                cat_img2 = load_cat_sticker(cat_path_2, (165, 165))
                if cat_img2:
                    paste_x2 = 930 - cat_img2.width // 2
                    paste_y2 = 1040 - cat_img2.height // 2
                    image.alpha_composite(cat_img2, dest=(paste_x2, paste_y2))

            except Exception as e:
                print(f"Failed to process cat images: {e}")
                pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = image.convert("RGB")
    image.save(output_path, format="PNG", optimize=True)
    return output_path
