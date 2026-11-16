from __future__ import annotations

import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORANGE = "#D4813F"
INK = "#0D0D0D"
SURFACE = "#151515"
PANEL = "#1B1B1B"
LINE = "#303030"
WHITE = "#F2F2F2"
MUTED = "#8A8A8A"


def correct_desktop() -> None:
    paths = [
        *sorted((ROOT / "desktop_wireframes").glob("*.svg")),
        ROOT / "Kola_Market_Desktop_Wireframes.svg",
    ]
    for path in paths:
        source = path.read_text()

        def fix_text(match: re.Match[str]) -> str:
            tag = match.group(0)
            tag = re.sub(r"KALA MARKET", "KOLA MARKET", tag, flags=re.I)
            if re.search(r'fill="#777777"', tag, re.I):
                tag = re.sub(r'fill="#777777"', f'fill="{MUTED}"', tag, flags=re.I)
                size = re.search(r'font-size="([0-9.]+)"', tag)
                if size and float(size.group(1)) < 11:
                    tag = tag[: size.start(1)] + "11" + tag[size.end(1) :]
            return tag

        # Footer labels live in text-node contents, so match complete SVG text
        # elements instead of only their opening tags.
        path.write_text(
            re.sub(r"<text\b[^>]*>.*?</text>", fix_text, source, flags=re.I | re.S)
        )


def svg_text(
    x: int, y: int, value: str, size: int = 13, color: str = WHITE, weight: int = 400
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Inter,Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{escape(value)}</text>'
    )


def rect(
    x: int,
    y: int,
    w: int,
    h: int,
    fill: str = PANEL,
    stroke: str = LINE,
    radius: int = 8,
) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    )


def make_mobile(
    name: str,
    title: str,
    route: str,
    width: int,
    body: str,
    public: bool = False,
    ops: bool = False,
) -> str:
    inset = 16
    inner = width - 2 * inset
    header = (
        f'<rect width="{width}" height="64" fill="{INK}" stroke="{LINE}"/>'
        + svg_text(16, 27, "K", 20, ORANGE, 800)
        + svg_text(42, 26, "KOLA MARKET", 12, WHITE, 700)
        + svg_text(width - 92, 27, "⌕   ☰", 18, WHITE, 500)
        + svg_text(16, 52, "SECURE MARKETPLACE", 11, MUTED, 500)
    )
    nav = (
        [
            (18, "QUEUE"),
            (width * 0.28, "RESERVES"),
            (width * 0.55, "VENDORS"),
            (width - 76, "HEALTH"),
        ]
        if ops
        else (
            [
                (18, "BROWSE"),
                (width * 0.29, "SEARCH"),
                (width * 0.55, "CART"),
                (width - 76, "ACCOUNT"),
            ]
            if public
            else [
                (18, "BROWSE"),
                (width * 0.29, "ORDERS"),
                (width * 0.55, "BALANCE"),
                (width - 76, "PROFILE"),
            ]
        )
    )
    footer = (
        f'<rect x="0" y="828" width="{width}" height="72" fill="{INK}" stroke="{LINE}"/>'
        + "".join(svg_text(x, 853, label, 11, MUTED, 600) for x, label in nav)
        + svg_text(16, 879, "KOLA MARKET  ·  MOBILE  ·  375 PX", 11, MUTED, 500)
    )
    if width == 320:
        footer = footer.replace("375 PX", "320 PX")
    content = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="900" '
        f'viewBox="0 0 {width} 900">'
        + f'<rect width="{width}" height="900" fill="{INK}"/>'
        + header
        + svg_text(inset, 105, title, 23, WHITE, 700)
        + svg_text(inset, 129, route, 11, MUTED, 500)
        + body
        + footer
        + "</svg>"
    )
    return content


def card(y: int, h: int, width: int = 375, fill: str = SURFACE) -> str:
    return rect(16, y, width - 32, h, fill)


def button(y: int, label: str, width: int = 375) -> str:
    return rect(16, y, width - 32, 46, ORANGE, ORANGE, 6) + svg_text(
        32, y + 29, label, 13, INK, 700
    )


def row(y: int, left: str, right: str, width: int = 375) -> str:
    right_text = (
        f'<text x="{width - 30}" y="{y}" text-anchor="end" '
        f'font-family="Inter,Arial,sans-serif" font-size="12" '
        f'font-weight="600" fill="{WHITE}">{escape(right)}</text>'
    )
    return svg_text(30, y, left, 12, MUTED, 500) + right_text


def generate_mobile() -> None:
    out = ROOT / "mobile_wireframes"
    gray = ROOT / "mobile_wireframes_grayscale"
    out.mkdir(exist_ok=True)
    gray.mkdir(exist_ok=True)
    screens: list[tuple[str, str]] = []

    b = card(150, 112) + svg_text(30, 176, "STATUS FILTERS", 11, MUTED, 600)
    b += svg_text(30, 204, "ALL     IN ESCROW     CONFIRMED", 11, WHITE, 600)
    b += card(278, 198) + svg_text(30, 306, "ORD-2048", 12, WHITE, 700)
    b += svg_text(30, 333, "IN ESCROW", 11, ORANGE, 700)
    b += svg_text(30, 365, "Handcrafted walnut desk", 14, WHITE, 600)
    b += svg_text(30, 390, "Vendor · northstar", 11, MUTED, 500)
    b += row(422, "TOTAL", "125.00 XMR")
    b += svg_text(30, 456, "Escrow progress  ·  2 of 3", 11, MUTED, 500)
    b += rect(30, 470, 279, 5, ORANGE, ORANGE, 3)
    b += svg_text(30, 499, "View order details  →", 12, WHITE, 600)
    b += svg_text(
        16, 535, "Tables collapse to stacked record cards on mobile.", 11, MUTED, 400
    )
    screens.append(
        ("01-order-list.svg", make_mobile("Orders", "Your orders", "/orders/", 375, b))
    )

    b = card(151, 132) + svg_text(30, 180, "ORD-2048", 14, WHITE, 700)
    b += svg_text(30, 207, "IN ESCROW", 11, ORANGE, 700) + row(
        245, "ORDER TOTAL", "125.00 XMR"
    )
    b += card(299, 144) + svg_text(30, 332, "ESCROW · 2 OF 3", 11, MUTED, 700)
    b += svg_text(30, 364, "✓  Deposit confirmed", 12, WHITE, 500)
    b += svg_text(30, 394, "✓  Vendor marked shipped", 12, WHITE, 500)
    b += svg_text(30, 424, "○  Buyer confirms delivery", 12, ORANGE, 600)
    b += svg_text(16, 480, "Shipping and evidence", 16, WHITE, 650)
    b += card(500, 86) + svg_text(30, 534, "Tracking · PKG-5931", 12, WHITE, 500)
    b += svg_text(30, 560, "Last updated today at 10:42", 11, MUTED, 500)
    b += button(613, "CONFIRM RECEIPT")
    b += svg_text(16, 684, "Need help? Open a dispute", 12, MUTED, 500)
    screens.append(
        (
            "02-order-detail.svg",
            make_mobile("Order detail", "Order details", "/orders/2048/", 375, b),
        )
    )

    b = card(150, 143) + svg_text(30, 184, "ORDER SUMMARY", 11, MUTED, 700)
    b += svg_text(30, 215, "Handcrafted walnut desk", 13, WHITE, 600)
    b += row(248, "QTY 1 · northstar", "110.00")
    b += row(278, "Delivery", "15.00")
    b += card(313, 101) + svg_text(30, 348, "DELIVERY ADDRESS", 11, MUTED, 700)
    b += svg_text(30, 376, "Nana K. · Nairobi, Kenya", 12, WHITE, 500)
    b += svg_text(30, 399, "Encrypted until order dispatch", 11, MUTED, 500)
    b += card(434, 110) + svg_text(30, 470, "2-OF-3 MULTISIG ESCROW", 11, ORANGE, 700)
    b += svg_text(30, 498, "Funds release after buyer confirmation", 11, WHITE, 500)
    b += row(527, "TOTAL", "125.00 XMR")
    b += button(574, "CONFIRM & CREATE ORDER")
    b += svg_text(16, 648, "Review details before committing funds.", 11, MUTED, 500)
    screens.append(
        (
            "03-checkout-confirm.svg",
            make_mobile(
                "Checkout", "Confirm checkout", "/catalog/checkout/confirm/", 375, b
            ),
        )
    )

    b = card(150, 115) + svg_text(30, 184, "AVAILABLE BALANCE", 11, MUTED, 700)
    b += svg_text(30, 224, "42.500 XMR", 23, WHITE, 700)
    b += svg_text(30, 247, "Deposits are confirmed on-chain", 11, MUTED, 500)
    b += card(284, 120) + svg_text(30, 319, "DEPOSIT NETWORK", 11, MUTED, 700)
    b += svg_text(30, 350, "MONERO (XMR)  ·  CONFIRMED", 12, ORANGE, 650)
    b += svg_text(30, 381, "Address", 11, MUTED, 500)
    b += svg_text(30, 406, "84...kP9  [ COPY ]", 12, WHITE, 600)
    b += card(422, 91) + svg_text(30, 458, "Recent deposit", 12, WHITE, 600)
    b += svg_text(30, 487, "0.250 XMR  ·  CONFIRMED", 11, MUTED, 500)
    b += button(544, "CREATE NEW DEPOSIT ADDRESS")
    screens.append(
        (
            "04-deposit-panel.svg",
            make_mobile("Deposits", "Add funds", "/accounts/profile/deposits/", 375, b),
        )
    )

    b = card(150, 91) + svg_text(30, 185, "AVAILABLE TO WITHDRAW", 11, MUTED, 700)
    b += svg_text(30, 220, "42.500 XMR", 21, WHITE, 700)
    b += svg_text(16, 275, "Amount", 12, WHITE, 600) + rect(
        16, 288, 343, 48, PANEL, LINE, 5
    )
    b += svg_text(30, 318, "0.000 XMR", 13, MUTED, 500)
    b += svg_text(16, 369, "Payout address", 12, WHITE, 600) + rect(
        16, 382, 343, 58, PANEL, LINE, 5
    )
    b += svg_text(30, 407, "84...kP9", 12, WHITE, 500) + svg_text(
        30, 428, "Verified Monero address", 11, MUTED, 500
    )
    b += card(457, 82) + svg_text(30, 491, "SECURITY REVIEW", 11, ORANGE, 700)
    b += svg_text(30, 519, "PGP confirmation required", 11, WHITE, 500)
    b += button(562, "REQUEST WITHDRAWAL")
    b += svg_text(16, 635, "Typical review: within 24 hours", 11, MUTED, 500)
    screens.append(
        (
            "05-withdrawal-form.svg",
            make_mobile(
                "Withdrawal", "Withdraw funds", "/accounts/profile/withdrawals/", 375, b
            ),
        )
    )

    b = card(150, 92) + svg_text(30, 184, "ORD-2048  ·  IN ESCROW", 12, ORANGE, 700)
    b += svg_text(30, 211, "Delivery issue · opened today", 11, MUTED, 500)
    b += card(260, 112) + svg_text(30, 295, "BUYER · 10:42", 11, MUTED, 600)
    b += svg_text(30, 325, "Package arrived damaged. Photos", 12, WHITE, 500)
    b += svg_text(30, 348, "attached for review.", 12, WHITE, 500)
    b += card(389, 90) + svg_text(30, 423, "VENDOR · 11:05", 11, MUTED, 600)
    b += svg_text(30, 453, "Please upload the outer packaging too.", 11, WHITE, 500)
    b += svg_text(16, 514, "Add evidence", 14, WHITE, 650)
    b += rect(16, 529, 343, 82, PANEL, LINE, 5) + svg_text(
        30, 558, "Write a reply…", 12, MUTED, 500
    )
    b += rect(16, 623, 343, 42, SURFACE, LINE, 5) + svg_text(
        30, 650, "+  ATTACH FILE", 11, WHITE, 600
    )
    b += button(680, "SUBMIT EVIDENCE")
    screens.append(
        (
            "06-dispute-thread.svg",
            make_mobile(
                "Dispute", "Dispute thread", "/orders/dispute/2048/evidence/", 375, b
            ),
        )
    )

    b = card(150, 100) + svg_text(30, 184, "OPEN DISPUTES", 11, MUTED, 700)
    b += svg_text(30, 220, "7", 24, WHITE, 700) + svg_text(
        72, 218, "2 awaiting review", 12, ORANGE, 600
    )
    b += card(269, 211) + svg_text(30, 304, "ORD-2048", 13, WHITE, 700)
    b += svg_text(30, 333, "HIGH PRIORITY", 11, ORANGE, 700)
    b += svg_text(30, 365, "Delivery issue · 2 parties", 12, WHITE, 500)
    b += svg_text(30, 392, "Last activity · 11:05", 11, MUTED, 500)
    b += row(431, "ESCROW", "125.00 XMR")
    b += rect(30, 454, 295, 1, LINE, LINE, 0)
    b += svg_text(30, 488, "Review evidence and timeline", 11, MUTED, 500)
    b += rect(30, 507, 137, 42, SURFACE, LINE, 5) + svg_text(
        47, 534, "OPEN CASE", 11, WHITE, 650
    )
    b += rect(182, 507, 143, 42, ORANGE, ORANGE, 5) + svg_text(
        199, 534, "RULE DISPUTE", 11, INK, 700
    )
    b += svg_text(16, 574, "Ops actions require staff authentication.", 11, MUTED, 500)
    screens.append(
        (
            "07-admin-dispute-queue.svg",
            make_mobile(
                "Ops queue", "Dispute queue", "/orders/review/", 375, b, ops=True
            ),
        )
    )

    b = card(151, 158, fill="#28231E") + svg_text(
        30, 224, "LISTING IMAGE", 11, MUTED, 650
    )
    b += svg_text(30, 276, "PHOTO / GALLERY 01", 11, WHITE, 500)
    b += svg_text(16, 342, "Handcrafted walnut desk", 19, WHITE, 700)
    b += svg_text(16, 372, "by northstar  ·  ★ 4.9 (28)", 12, MUTED, 500)
    b += svg_text(16, 419, "110.00 XMR", 21, ORANGE, 700)
    b += svg_text(16, 444, "Buyer protection · 2-of-3 escrow", 11, MUTED, 500)
    b += card(470, 95) + svg_text(30, 507, "IN STOCK", 11, ORANGE, 700)
    b += svg_text(30, 536, "Ships in 2–4 business days", 12, WHITE, 500)
    b += button(589, "ADD TO CART")
    b += svg_text(16, 671, "Details     Shipping     Reviews", 11, MUTED, 600)
    screens.append(
        (
            "08-listing-detail.svg",
            make_mobile(
                "Listing", "Listing detail", "/catalog/listings/2048/", 375, b, True
            ),
        )
    )

    b = rect(16, 83, 343, 48, PANEL, LINE, 6) + svg_text(
        31, 113, "⌕  Search listings…", 13, MUTED, 500
    )
    b += svg_text(16, 168, "Browse categories", 18, WHITE, 700)
    b += card(187, 85) + svg_text(30, 224, "HANDMADE GOODS", 12, WHITE, 650)
    b += svg_text(30, 251, "Trusted makers · escrow protected", 11, MUTED, 500)
    b += svg_text(16, 309, "Popular this week", 16, WHITE, 650)
    b += card(327, 176) + svg_text(30, 379, "LISTING PHOTO", 11, MUTED, 500)
    b += svg_text(30, 440, "Handcrafted walnut desk", 13, WHITE, 600)
    b += svg_text(30, 471, "110.00 XMR", 14, ORANGE, 700)
    b += svg_text(30, 498, "northstar  ·  ★ 4.9", 11, MUTED, 500)
    b += card(526, 78) + svg_text(
        30, 561, "Search is collapsed to an icon in the header.", 11, WHITE, 500
    )
    b += svg_text(30, 587, "Tap to expand without shifting the page.", 11, MUTED, 500)
    screens.append(
        (
            "09-header-search-collapsed.svg",
            make_mobile("Collapsed search", "Discover", "/", 375, b, True),
        )
    )

    b = card(150, 112, width=320) + svg_text(30, 176, "STATUS FILTERS", 11, MUTED, 600)
    b += svg_text(30, 204, "ALL   ESCROW   CONFIRMED", 11, WHITE, 600)
    b += card(278, 206, width=320) + svg_text(30, 306, "ORD-2048", 12, WHITE, 700)
    b += svg_text(30, 333, "IN ESCROW", 11, ORANGE, 700)
    b += svg_text(30, 363, "Walnut desk · northstar", 12, WHITE, 600)
    b += row(396, "TOTAL", "125.00 XMR", 320)
    b += svg_text(30, 430, "Escrow progress · 2 of 3", 11, MUTED, 500)
    b += rect(30, 444, 242, 5, ORANGE, ORANGE, 3)
    b += svg_text(30, 478, "View details  →", 12, WHITE, 600)
    b += svg_text(16, 525, "No horizontal table scrolling.", 11, MUTED, 500)
    b += svg_text(16, 552, "Actions remain full-width and reachable.", 11, MUTED, 500)
    screens.append(
        (
            "10-order-list-320px.svg",
            make_mobile("320px order list", "Your orders", "/orders/", 320, b),
        )
    )

    for filename, source in screens:
        (out / filename).write_text(source)
        gray_svg = re.sub(r"#[0-9A-Fa-f]{6}", lambda m: grayscale(m.group(0)), source)
        (gray / filename).write_text(gray_svg)

    # A compact, labeled sheet with each phone view kept at its natural width.
    sheet_w, sheet_h = 790, 5 * 960 + 40
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{sheet_w}" height="{sheet_h}" viewBox="0 0 {sheet_w} {sheet_h}">',
        f'<rect width="{sheet_w}" height="{sheet_h}" fill="{INK}"/>',
        svg_text(24, 32, "KOLA MARKET · MOBILE PINCH-POINTS", 16, WHITE, 700),
    ]
    for i, (filename, source) in enumerate(screens):
        col, row_i = i % 2, i // 2
        x, y = 12 + col * 390, 48 + row_i * 960
        match = re.match(r"<svg[^>]*>(.*)</svg>", source, re.S)
        parts.append(f'<g transform="translate({x} {y})">{match.group(1)}</g>')
    parts.append("</svg>")
    sheet = "".join(parts)
    (out / "contact-sheet.svg").write_text(sheet)
    (gray / "contact-sheet.svg").write_text(
        re.sub(r"#[0-9A-Fa-f]{6}", lambda m: grayscale(m.group(0)), sheet)
    )


def grayscale(color: str) -> str:
    rgb = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    value = round(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2])
    return f"#{value:02X}{value:02X}{value:02X}"


def generate_desktop_grayscale() -> None:
    out = ROOT / "desktop_wireframes_grayscale"
    out.mkdir(exist_ok=True)
    for path in sorted((ROOT / "desktop_wireframes").glob("*.svg")):
        source = path.read_text()
        gray = re.sub(r"#[0-9A-Fa-f]{6}", lambda m: grayscale(m.group(0)), source)
        (out / path.name).write_text(gray)
    source = (ROOT / "Kola_Market_Desktop_Wireframes.svg").read_text()
    gray = re.sub(r"#[0-9A-Fa-f]{6}", lambda m: grayscale(m.group(0)), source)
    (ROOT / "Kola_Market_Desktop_Wireframes_grayscale.svg").write_text(gray)


if __name__ == "__main__":
    correct_desktop()
    generate_mobile()
    generate_desktop_grayscale()
