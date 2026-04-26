"""Generate a 512x512 movie recommendation channel logo."""

import math
from PIL import Image, ImageDraw


def draw_star(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    outer: float,
    inner: float,
    points: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    outline_width: int = 2,
) -> None:
    """Draw a regular star polygon."""
    coords: list[tuple[float, float]] = []
    for i in range(points * 2):
        angle = math.pi / points * i - math.pi / 2
        r = outer if i % 2 == 0 else inner
        coords.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(coords, fill=fill)
    if outline:
        draw.line(coords + [coords[0]], fill=outline, width=outline_width)


def draw_film_reel(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    radius: float,
    color_outer: tuple[int, int, int, int],
    color_inner: tuple[int, int, int, int],
    color_bg: tuple[int, int, int, int],
    color_hole: tuple[int, int, int, int],
) -> None:
    """Draw a film reel using circles and arc segments."""
    # Outer ring
    r = radius
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=color_outer,
    )

    # Sprocket holes around the rim (8 holes)
    hole_r = r * 0.10
    orbit = r * 0.78
    for i in range(8):
        angle = math.pi * 2 / 8 * i
        hx = cx + orbit * math.cos(angle)
        hy = cy + orbit * math.sin(angle)
        draw.ellipse(
            [hx - hole_r, hy - hole_r, hx + hole_r, hy + hole_r],
            fill=color_bg,
        )

    # Inner disk
    inner_r = r * 0.58
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=color_inner,
    )

    # Film frame segments (6 sectors separated by thin gaps)
    seg_outer = inner_r * 0.95
    seg_inner = inner_r * 0.42
    gap_deg = 8  # degrees gap between segments
    for i in range(6):
        start_angle = 360 / 6 * i + gap_deg / 2 - 90
        end_angle = start_angle + 360 / 6 - gap_deg
        # Draw filled arc segment via polygon approximation
        pts: list[tuple[float, float]] = []
        steps = 30
        for s in range(steps + 1):
            a = math.radians(start_angle + (end_angle - start_angle) * s / steps)
            pts.append((cx + seg_outer * math.cos(a), cy + seg_outer * math.sin(a)))
        for s in range(steps, -1, -1):
            a = math.radians(start_angle + (end_angle - start_angle) * s / steps)
            pts.append((cx + seg_inner * math.cos(a), cy + seg_inner * math.sin(a)))
        draw.polygon(pts, fill=color_outer)

    # Center hub
    hub_r = inner_r * 0.30
    draw.ellipse(
        [cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
        fill=color_hole,
    )
    # Tiny center hole
    tiny_r = hub_r * 0.40
    draw.ellipse(
        [cx - tiny_r, cy - tiny_r, cx + tiny_r, cy + tiny_r],
        fill=color_bg,
    )


def main() -> None:
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2

    # --- Background: dark blue circle ---
    bg_color: tuple[int, int, int, int] = (26, 26, 46, 255)       # #1a1a2e
    rim_color: tuple[int, int, int, int] = (22, 33, 62, 255)       # #16213e
    draw.ellipse([0, 0, size, size], fill=rim_color)
    margin = 18
    draw.ellipse([margin, margin, size - margin, size - margin], fill=bg_color)

    # --- Subtle radial gradient rings (layered circles) ---
    for i in range(6):
        r_ring = 220 - i * 18
        alpha = 18 + i * 4
        ring_color = (58, 78, 140, alpha)
        ring_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring_img)
        ring_draw.ellipse(
            [cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring],
            outline=ring_color,
            width=2,
        )
        img = Image.alpha_composite(img, ring_img)

    draw = ImageDraw.Draw(img)

    # --- Film reel (centered, slightly above center to leave room for star) ---
    reel_cx, reel_cy = cx, cy + 10
    reel_radius = 148

    outer_col: tuple[int, int, int, int] = (58, 78, 140, 255)     # blue-steel
    inner_col: tuple[int, int, int, int] = (36, 48, 90, 255)      # darker
    hole_col: tuple[int, int, int, int] = (80, 100, 180, 255)

    draw_film_reel(
        draw,
        reel_cx, reel_cy,
        reel_radius,
        outer_col,
        inner_col,
        bg_color,
        hole_col,
    )

    # --- Outer reel edge highlight ---
    for w, alpha in [(3, 90), (1, 160)]:
        draw.ellipse(
            [
                reel_cx - reel_radius,
                reel_cy - reel_radius,
                reel_cx + reel_radius,
                reel_cy + reel_radius,
            ],
            outline=(120, 150, 230, alpha),
            width=w,
        )

    # --- Golden star (top-center, overlapping reel) ---
    star_cx = cx
    star_cy = cy - 108
    star_outer = 72
    star_inner = 29

    # Glow layers
    glow_colors: list[tuple[int, int, int, int]] = [
        (255, 200, 50, 18),
        (255, 200, 50, 35),
        (255, 180, 30, 55),
    ]
    for idx, gc in enumerate(glow_colors):
        glow_r = star_outer + 28 - idx * 8
        draw.ellipse(
            [star_cx - glow_r, star_cy - glow_r, star_cx + glow_r, star_cy + glow_r],
            fill=gc,
        )

    # Shadow behind star
    draw_star(
        draw, star_cx + 3, star_cy + 4,
        star_outer, star_inner, 5,
        fill=(0, 0, 0, 90),
    )

    # Main gold star
    draw_star(
        draw, star_cx, star_cy,
        star_outer, star_inner, 5,
        fill=(255, 200, 40, 255),
        outline=(255, 230, 120, 220),
        outline_width=2,
    )

    # Highlight on star (top-left facet)
    draw_star(
        draw, star_cx - 4, star_cy - 4,
        star_outer * 0.55, star_inner * 0.55, 5,
        fill=(255, 240, 160, 80),
    )

    # --- Small accent stars (scattered) ---
    accent_positions = [
        (72, 95, 9, 4),
        (440, 110, 7, 3),
        (88, 400, 6, 2),
        (435, 390, 8, 3),
        (260, 55, 5, 2),
        (160, 440, 6, 2),
        (370, 445, 5, 2),
    ]
    for ax, ay, ao, ai in accent_positions:
        draw_star(
            draw, ax, ay, ao, ai, 5,
            fill=(255, 200, 40, 180),
        )

    # --- Film strip at bottom ---
    strip_y = size - 62
    strip_h = 38
    strip_color: tuple[int, int, int, int] = (40, 52, 100, 230)
    draw.rectangle([24, strip_y, size - 24, strip_y + strip_h], fill=strip_color)

    # Frame dividers
    frame_w = 32
    frame_h = 22
    frame_gap = 6
    frame_y = strip_y + (strip_h - frame_h) // 2
    frame_color: tuple[int, int, int, int] = (26, 26, 46, 255)
    x_pos = 40
    while x_pos + frame_w < size - 30:
        draw.rectangle(
            [x_pos, frame_y, x_pos + frame_w, frame_y + frame_h],
            fill=frame_color,
            outline=(80, 100, 180, 160),
            width=1,
        )
        x_pos += frame_w + frame_gap

    # Perforations top & bottom of strip
    perf_r = 4
    perf_y_top = strip_y + 5
    perf_y_bot = strip_y + strip_h - 10
    px = 35
    while px < size - 30:
        for py in [perf_y_top, perf_y_bot]:
            draw.ellipse(
                [px, py, px + perf_r * 2, py + perf_r * 2],
                fill=(26, 26, 46, 220),
            )
        px += 16

    # Strip highlight
    draw.rectangle(
        [24, strip_y, size - 24, strip_y + 2],
        fill=(100, 130, 220, 120),
    )

    # --- Save ---
    output_path = "/Users/admin/movie-recommender/logo.png"
    img.save(output_path, "PNG")
    print(f"Saved: {output_path} ({size}x{size})")


if __name__ == "__main__":
    main()
