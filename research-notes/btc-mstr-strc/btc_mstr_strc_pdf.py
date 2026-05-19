import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.flowables import Flowable

# ── Font registration ──────────────────────────────────────────────────────
FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts"),
]

def find_font(names):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None

arial       = find_font(["arial.ttf",    "Arial.ttf"])
arial_bold  = find_font(["arialbd.ttf",  "Arial Bold.ttf", "arialb.ttf"])
arial_it    = find_font(["ariali.ttf",   "Arial Italic.ttf"])
arial_bi    = find_font(["arialbi.ttf",  "Arial Bold Italic.ttf"])

pdfmetrics.registerFont(TTFont("Arial",            arial))
pdfmetrics.registerFont(TTFont("Arial-Bold",       arial_bold))
if arial_it:
    pdfmetrics.registerFont(TTFont("Arial-Italic",     arial_it))
if arial_bi:
    pdfmetrics.registerFont(TTFont("Arial-BoldItalic", arial_bi))
pdfmetrics.registerFontFamily(
    "Arial",
    normal="Arial",
    bold="Arial-Bold",
    italic="Arial-Italic" if arial_it else "Arial",
    boldItalic="Arial-BoldItalic" if arial_bi else "Arial-Bold",
)

# ── Colours ────────────────────────────────────────────────────────────────
NAVY     = colors.HexColor("#1A1A2E")
GRAY     = colors.HexColor("#666666")
LGRAY    = colors.HexColor("#EEEEEE")
BTC_ORG  = colors.HexColor("#F7931A")
WHITE    = colors.white
BLACK    = colors.black

C_BEAR   = colors.HexColor("#FFF0F0")
C_BASE   = colors.HexColor("#F7F7F7")
C_BULL   = colors.HexColor("#F0FFF0")
C_BLEND  = colors.HexColor("#F0F0FF")
C_HDR    = colors.HexColor("#E8E8F0")

# ── Styles ─────────────────────────────────────────────────────────────────
def S(name, **kw):
    defaults = dict(fontName="Arial", fontSize=9.5, leading=13, textColor=BLACK)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)

sNormal   = S("Normal")
sBold     = S("Bold",     fontName="Arial-Bold")
sSection  = S("Section",  fontName="Arial-Bold", fontSize=11, textColor=NAVY,
               spaceBefore=14, spaceAfter=4)
sSubSec   = S("SubSec",   fontName="Arial-Bold", fontSize=9.5, textColor=NAVY,
               spaceBefore=8, spaceAfter=2)
sMono     = S("Mono",     fontName="Arial", fontSize=8.5, leading=12,
               textColor=colors.HexColor("#2C2C5E"))
sSmall    = S("Small",    fontSize=8, textColor=GRAY)
sBullet   = S("Bullet",   leftIndent=12, firstLineIndent=0)
sFlag     = S("Flag",     fontSize=9, leading=12, textColor=colors.HexColor("#8B0000"))

sCoverTitle  = S("CoverTitle",  fontName="Arial-Bold", fontSize=28, textColor=NAVY,
                  leading=34, spaceAfter=6)
sCoverSub    = S("CoverSub",    fontName="Arial-Bold", fontSize=14, textColor=GRAY,
                  leading=18, spaceAfter=4)
sCoverTag    = S("CoverTag",    fontSize=9.5, textColor=GRAY, spaceAfter=14)
sCoverTOC    = S("CoverTOC",   fontSize=9, textColor=GRAY, leading=14)

sTH = S("TH", fontName="Arial-Bold", fontSize=8.5, textColor=NAVY)
sTD = S("TD", fontSize=8.5, leading=11)
sTDsm = S("TDsm", fontSize=8, leading=10, textColor=GRAY)

# ── Colored block helper ───────────────────────────────────────────────────
class ColorBlock(Flowable):
    """Full-width colored background block."""
    def __init__(self, story_items, bg_color, padding=6):
        super().__init__()
        self._items = story_items
        self._bg = bg_color
        self._pad = padding

    def wrap(self, aW, aH):
        self._aW = aW
        return aW, 0  # height determined at draw time

    def draw(self):
        pass  # handled via Table with background

def colored_block(content_paragraphs, bg_color, col_width=6.0*inch):
    """Wrap paragraphs in a single-cell table with colored background."""
    inner = [[p] for p in content_paragraphs]
    # Flatten to single cell
    cell_content = content_paragraphs
    t = Table([[cell_content]], colWidths=[col_width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg_color),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    return t

# ── Header / Footer ────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
LM = RM = 1.25 * inch
TM = BM = 1.0  * inch
BODY_W = PAGE_W - LM - RM  # 6.0 inches

def on_page(canvas, doc):
    canvas.saveState()
    # Header
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(GRAY)
    hdr = "SINGLE-STOCK DEEP DIVE   BTC / MSTR / STRC   2026-05-19"
    canvas.drawRightString(PAGE_W - RM, PAGE_H - 0.65*inch, hdr)
    # Footer
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(GRAY)
    ftr = f"FOR FRENS AND FAMILIE ONLY — not for distribution — 2026-05-19 — Page {doc.page}"
    canvas.drawCentredString(PAGE_W / 2, 0.55*inch, ftr)
    canvas.restoreState()

# ── Table builder helper ───────────────────────────────────────────────────
def make_table(headers, rows, col_widths, src_note=None):
    data = [[Paragraph(h, sTH) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), sTD) for c in row])
    if src_note:
        colspan = len(headers)
        data.append([Paragraph(src_note, sTDsm)] + [""] * (colspan - 1))

    style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  C_HDR),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, NAVY),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.3, LGRAY),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [WHITE, colors.HexColor("#F9F9FB")]),
        ("TOPPADDING",    (0, 0), (-1, -1),  4),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  4),
        ("LEFTPADDING",   (0, 0), (-1, -1),  6),
        ("RIGHTPADDING",  (0, 0), (-1, -1),  6),
        ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ("GRID",          (0, 0), (-1, -1),  0.25, LGRAY),
    ]
    if src_note:
        style += [
            ("SPAN",       (0, -1), (-1, -1)),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F5F5F5")),
        ]

    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style))
    return t

# ── Trade line helper ──────────────────────────────────────────────────────
def trade_row(label, content):
    """Render a single → LABEL   content trade line."""
    arrow = Paragraph(f"<b>→ {label}</b>", S("TL", fontName="Arial-Bold",
                       fontSize=9, textColor=NAVY))
    body  = Paragraph(content, S("TC", fontSize=9, leading=12))
    t = Table([[arrow, body]], colWidths=[1.35*inch, 4.65*inch])
    t.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (0,-1),  0),
        ("LEFTPADDING",   (1,0), (1,-1),  6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        ("LINEABOVE",     (0,0), (-1,0),  0.25, LGRAY),
    ]))
    return t

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=6, spaceBefore=6)

def section(title):
    return Paragraph(title, sSection)

def subsection(title):
    return Paragraph(title, sSubSec)

def body(text):
    return Paragraph(text, sNormal)

def sp(n=6):
    return Spacer(1, n)

# ── Build story ────────────────────────────────────────────────────────────
story = []

# ════════════════════════════════════════════════════════════════════════════
# COVER
# ════════════════════════════════════════════════════════════════════════════
story.append(Spacer(1, 0.8*inch))
story.append(Paragraph("Strategy Capital Stack", sCoverTitle))
story.append(Paragraph("Three Ways to Own Bitcoin", sCoverSub))
story.append(hr())
story.append(Paragraph("BTC · MSTR · STRC  —  2026-05-19    FOR FRENS AND FAMILIE ONLY", sCoverTag))
story.append(Spacer(1, 0.3*inch))
toc_text = (
    "<b>Contents</b><br/>"
    "01 Business Frame · 02 Competitive Position · 03 Financials · "
    "04 Valuation · 05 The Debate · 06 Positioning · "
    "07 Tradeable Expression · 08 What to Monitor<br/>"
    "VAL · SCENARIOS · SENSITIVITY · TRADES · SIZING · TIME-SENSITIVE FLAGS"
)
story.append(Paragraph(toc_text, sCoverTOC))
story.append(PageBreak())

# ════════════════════════════════════════════════════════════════════════════
# 01 — BUSINESS FRAME
# ════════════════════════════════════════════════════════════════════════════
story.append(section("01 — BUSINESS FRAME"))
story.append(body(
    "Strategy Inc (formerly MicroStrategy) operates a Bitcoin acquisition flywheel: "
    "issue equity (MSTR) and preferred stock (STRC) → deploy proceeds into BTC → "
    "rising BTC collateral supports further issuance. The company holds <b>843,738 BTC</b> as of "
    "May 18 2026 (CoinDesk, May 2026), acquired at an average cost of <b>$66,384/BTC</b>, "
    "total spend $33.14B (bitbo.io, May 2026). Strategy’s BTC holdings represent "
    "&gt;60% of all Bitcoin held by publicly listed companies globally (LambdaFin, 2026)."
))
story.append(sp())
story.append(body("Three instruments give different risk/return exposure to the same underlying:"))
for bullet in [
    "<b>BTC:</b> pure unlevered exposure, no corporate overhead, maximum convexity",
    "<b>MSTR:</b> leveraged equity, variable beta 1.8x–5x+ to BTC, mNAV premium/discount dynamics",
    "<b>STRC:</b> 11.5% perpetual preferred, trades near $100 par, capital structure senior to MSTR",
]:
    story.append(Paragraph(f"• {bullet}", sBullet))
story.append(sp())
story.append(body(
    "Revenue: TTM $477.2M, net income −$3.8B (unrealised BTC mark-to-market). "
    "Total liabilities: $10.60B. USD cash reserves for STRC dividends: <b>$2.25B</b> (21.8 months forward coverage)."
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 02 — COMPETITIVE POSITION
# ════════════════════════════════════════════════════════════════════════════
story.append(section("02 — COMPETITIVE POSITION"))
story.append(body(
    "The moat is the flywheel itself. At <b>$62.18B market cap</b> (Yahoo Finance, May 2026), "
    "Strategy commands disproportionate capital markets access at scale. No other listed entity "
    "approaches this BTC accumulation velocity — Strategy raised $25.3B in 2025 alone and "
    "targets 5–7% of total BTC supply (LambdaFin, 2026)."
))
story.append(sp())
story.append(body(
    "<b>MSTR’s advantage over direct BTC:</b> deep options liquidity, equity index inclusion, "
    "regulated structure for mandates that cannot hold spot BTC."
))
story.append(sp())
story.append(body(
    "<b>STRC’s advantage:</b> $8.5B market cap makes it the world’s largest preferred stock "
    "(Seeking Alpha, 2026). Adjustable yield mechanism actively defends par value. "
    "Ondo Finance has tokenised STRC on-chain at the same 11.5% yield (CCN, 2026)."
))
story.append(sp())
story.append(body(
    "<b>Vulnerabilities:</b> (1) BTC price is the only real fundamental — all metrics collapse to BTC/USD. "
    "(2) Ongoing ATM dilution compresses BTC per share unless offset by BTC appreciation. "
    "(3) Convertible holders rank ahead of preferred, who rank ahead of common."
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 03 — FINANCIALS
# ════════════════════════════════════════════════════════════════════════════
story.append(section("03 — FINANCIALS"))
story.append(subsection("MSTR / Strategy Inc — Key Metrics"))

mstr_rows = [
    ["BTC Holdings",      "~450,000",   "~766,970",   "~843,738"],
    ["Avg Cost/BTC",      "~$43,000",   "~$58,000",   "~$66,384"],
    ["BTC Yield YTD",     "N/A",        "N/A",        "9.4%"],
    ["TTM Revenue",       "N/A",        "N/A",        "$477.2M"],
    ["Net Income",        "N/A",        "N/A",        "−$3.8B"],
    ["Total Liabilities", "N/A",        "N/A",        "$10.60B"],
]
story.append(make_table(
    ["METRIC", "2024A", "2025A/E", "2026E"],
    mstr_rows,
    [2.4*inch, 1.2*inch, 1.2*inch, 1.2*inch],
    "Sources: CoinDesk May 2026, StockTitan May 2026, bitbo.io May 2026"
))
story.append(sp())
story.append(body(
    "<i>Note: P&amp;L is dominated by unrealised BTC MTM gains/losses. Revenue and net income are "
    "near-irrelevant; BTC per diluted share and mNAV are the operative metrics.</i>"
))
story.append(sp(8))

story.append(subsection("STRC Preferred — Key Metrics"))
strc_rows = [
    ["Par value",           "$100.00"],
    ["Current price",       "~$99.99 (StockTitan, May 8 2026)"],
    ["Annual yield",        "11.50% ($0.9583/share/month, paid monthly)"],
    ["Dividend coverage",   "$2.25B USD reserves (21.8 months)"],
    ["Instrument size",     "$8.5B (world’s largest preferred)"],
]
story.append(make_table(
    ["METRIC", "CURRENT"],
    strc_rows,
    [2.4*inch, 3.6*inch],
    "Sources: Seeking Alpha 2026, BitcoinMagazinePro 2026, CCN 2026"
))
story.append(sp(8))

story.append(subsection("BTC — On-Chain Snapshot"))
btc_rows = [
    ["Price",           "~$99,887 (see TIME-SENSITIVE FLAGS)"],
    ["All-Time High",   "$126,198 (October 6 2025, Statista)"],
    ["MVRV Z-Score",    "0.41 — near fair value (AhaSignals, 2026)"],
    ["MVRV Ratio",      "1.37 — mid-cycle healthy (AhaSignals, 2026)"],
]
story.append(make_table(
    ["METRIC", "CURRENT"],
    btc_rows,
    [2.4*inch, 3.6*inch],
    "Sources: Fortune May 2026, AhaSignals 2026, MacroMicro 2026"
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 04 — VALUATION
# ════════════════════════════════════════════════════════════════════════════
story.append(section("04 — VALUATION"))
story.append(subsection("MSTR — mNAV Premium Framework"))
mnav_rows = [
    ["Bear trough",  "0.97x (Nov 2025)",    "$60k–$70k range", "~$130"],
    ["Current",      "~1.16x–1.23x",   "~$100k",              "~$177"],
    ["2024 peak",    "2.8x",                "$100k+",              "$500+"],
    ["Bull target",  "2.0x–2.5x",      "$150k+",              "$450–$550"],
]
story.append(make_table(
    ["SCENARIO", "mNAV MULTIPLE", "BTC PRICE", "MSTR EQUITY"],
    mnav_rows,
    [1.6*inch, 1.5*inch, 1.5*inch, 1.4*inch],
    "Sources: Investing.com Mar 2026, TheBlock data, 247WallSt Apr 2026"
))
story.append(sp())
story.append(body(
    "The mNAV compression from 2.8x to 1.16x is the central valuation story. At 1.16x, "
    "MSTR trades near NAV — either a floor (if BTC re-rates) or still elevated (if BTC declines)."
))
story.append(sp())
story.append(body(
    "<b>STRC — Yield Framework:</b> At $99.99, yield-to-perpetuity is <b>11.5%</b>. "
    "Attractive vs. IG credit (~5.5–6.0%) and HY (~7.5–8.0%), but appropriate given structural "
    "subordination to convertibles and BTC-dependent long-term coverage. Risk is asymmetric: "
    "above $60k BTC, clip 11.5%; below $40k–$50k, flywheel breaks and coverage becomes uncertain."
))
story.append(sp())
story.append(body(
    "<b>BTC — On-Chain Valuation:</b> MVRV ratio 1.37 and Z-Score 0.41 indicate mid-cycle. "
    "Historically, MVRV &gt;3.5 marks cycle tops; &lt;1.0 marks bottoms. At 1.37, meaningful upside "
    "capacity without imminent top signal (AhaSignals, MacroMicro, 2026)."
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 05 — THE DEBATE
# ════════════════════════════════════════════════════════════════════════════
story.append(section("05 — THE DEBATE"))

bull_paras = [
    Paragraph("<b>BULL</b>", S("BullHdr", fontName="Arial-Bold", fontSize=9.5,
                                textColor=colors.HexColor("#006600"))),
    Paragraph(
        "The mNAV compression from 2.8x to 1.16x reflects post-ATH mean reversion, not structural repricing. "
        "As BTC recovers toward $120k–$150k, MSTR’s premium historically re-expands in bull legs. "
        "Analyst consensus of $374–376 (191% upside from April lows, 13 Buy/Strong Buy ratings — 247WallSt, Apr 2026) "
        "and asymmetric downside beta (BTC −22% YTD 2026 vs. MSTR −9.5% — Mitrade, Mar 2026) "
        "suggest institutional support at the NAV floor.", sNormal),
]
bear_paras = [
    Paragraph("<b>BEAR</b>", S("BearHdr", fontName="Arial-Bold", fontSize=9.5,
                                textColor=colors.HexColor("#8B0000"))),
    Paragraph(
        "The flywheel requires perpetual capital market access and BTC appreciation. "
        "With $10.60B in liabilities and no organic revenue backstop, a $60k BTC print exposes "
        "the cost basis, strains preferred dividend coverage, and risks MSTR re-rating to 0.8x–0.9x mNAV. "
        "The 11.31% short float (MarketBeat, May 2026) is mostly basis trades, but a violent BTC move down "
        "would force unwind.", sNormal),
]
view_paras = [
    Paragraph("<b>VIEW</b>", S("ViewHdr", fontName="Arial-Bold", fontSize=9.5,
                                textColor=NAVY)),
    Paragraph(
        "STRC is the most interesting instrument in the stack at current prices. At 11.5% yield with "
        "21.8 months cash coverage and par-defending yield mechanism, it offers structurally protected income "
        "with genuine downside buffer vs. MSTR common. Direct BTC is cleaner than MSTR at 1.16x mNAV. "
        "MSTR is compelling only on a re-expansion thesis to 2.0x+ — that requires BTC &gt;$130k and "
        "positive narrative momentum.", sNormal),
]

story.append(colored_block(bull_paras, C_BULL))
story.append(sp(4))
story.append(colored_block(bear_paras, C_BEAR))
story.append(sp(4))
story.append(colored_block(view_paras, C_BLEND))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 06 — POSITIONING
# ════════════════════════════════════════════════════════════════════════════
story.append(section("06 — POSITIONING"))
story.append(body(
    "<b>MSTR:</b> Short interest 11.31% of float (37.2M shares — MarketBeat, May 2026). "
    "Elevated, but CoinDesk (Feb 2026) confirms shorts are predominantly MSTR/BTC basis trades "
    "(long IBIT / short MSTR), not outright bearish. Jane Street confirmed paired long IBIT / short MSTR positions. "
    "This limits short squeeze risk but suppresses beta in sideways BTC environments."
))
story.append(sp())
story.append(body(
    "<i>Directional estimate:</i> Consensus long / slightly crowded — 13 Buy ratings, wide coverage. "
    "Not under-owned. The 191% upside to consensus is known."
))
story.append(sp())
story.append(body(
    "<b>STRC:</b> <i>Directional estimate:</i> Under-owned in traditional fixed-income mandates. "
    "Ondo Finance tokenisation expands to DeFi yield buyers. ATH daily volume of $1.5B on "
    "May 14 2026 (MEXC News) signals accelerating discovery."
))
story.append(sp())
story.append(body(
    "<b>BTC:</b> MVRV 1.37 = moderate holder profit. Not capitulation (&lt;1.0) and not euphoria (&gt;3.5). "
    "Mid-cycle recovery read."
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 07 — TRADEABLE EXPRESSION
# ════════════════════════════════════════════════════════════════════════════
story.append(section("07 — TRADEABLE EXPRESSION"))
story.append(subsection("Catalyst Calendar"))
for cat in [
    "(1) BTC price vs. $100k psychological level — ongoing test, May 2026",
    "(2) US Strategic Bitcoin Reserve policy signals — Q2/Q3 2026",
    "(3) MSTR next ATM raise + BTC purchase announcement — monthly cadence, next ~June 2026",
]:
    story.append(Paragraph(cat, sBullet))
story.append(sp())
story.append(body(
    "<b>Capital Stack Logic:</b> Own BTC directly if you want pure unlevered exposure. "
    "mNAV premium means MSTR adds corporate overhead at current prices. Own MSTR if BTC is above $100k "
    "and mNAV re-expansion to 2.0x+ is the thesis — equity beta then generates 3–5x BTC upside. "
    "Own STRC if you want BTC-adjacent income with capital structure priority — clip 11.5% monthly, "
    "accept no equity upside."
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# 08 — WHAT TO MONITOR
# ════════════════════════════════════════════════════════════════════════════
story.append(section("08 — WHAT TO MONITOR"))
monitors = [
    ("BTC PRICE LEVELS",  "$100k (resistance), $126k (ATH recovery), $60k (STRC coverage stress / MSTR NAV break)"),
    ("MSTR mNAV",         "TheBlock dashboard — watch for &gt;1.5x (bull signal) or &lt;1.0x (bear signal)"),
    ("STRC COVERAGE",     "USD reserve drawdown rate, announced monthly. Flag if below 12 months"),
    ("BTC FUNDING RATE",  "CoinGlass.com/FundingRate/BTC — &gt;0.10% 8hr = crowded longs, caution"),
    ("MVRV Z-SCORE",      "AhaSignals / MacroMicro — &gt;2.0 = rebalance; &lt;0 = accumulate"),
    ("SHORT INTEREST",    "MarketBeat MSTR — watch for basis trade unwind if BTC sustains &gt;$120k"),
    ("STRC VOLUME",       "$1.5B daily ATH on May 14 — sustained elevated volume = adoption signal"),
]
mon_data = [[Paragraph(k, sTH), Paragraph(v, sTD)] for k,v in monitors]
mon_t = Table(mon_data, colWidths=[1.7*inch, 4.3*inch])
mon_t.setStyle(TableStyle([
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [WHITE, colors.HexColor("#F9F9FB")]),
    ("GRID",          (0,0), (-1,-1), 0.25, LGRAY),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(mon_t)
story.append(PageBreak())

# ════════════════════════════════════════════════════════════════════════════
# VAL — FAIR VALUE CONSTRUCTION
# ════════════════════════════════════════════════════════════════════════════
story.append(section("VAL — FAIR VALUE CONSTRUCTION"))
val_data = [
    [Paragraph("METHOD", sTH), Paragraph("IMPLIED VALUE", sTH),
     Paragraph("WEIGHT", sTH), Paragraph("NOTE", sTH)],
    [Paragraph("BTC MVRV-implied FV", sTD),
     Paragraph("$95k–$115k", sTD),
     Paragraph("40%", sTD),
     Paragraph("MVRV 1.37 mid-cycle", sTD)],
    [Paragraph("MSTR mNAV 1.5x target", sTD),
     Paragraph("~$230", sTD),
     Paragraph("35%", sTD),
     Paragraph("[DIRECTIONAL ESTIMATE]", sTD)],
    [Paragraph("MSTR analyst consensus", sTD),
     Paragraph("$374–$376 avg", sTD),
     Paragraph("25%", sTD),
     Paragraph("13 Buy/1 Hold — 247WallSt/Yahoo Finance, Apr 2026", sTD)],
]
val_t = Table(val_data, colWidths=[1.6*inch, 1.3*inch, 0.8*inch, 2.3*inch])
val_t.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0),  C_HDR),
    ("LINEBELOW",     (0,0), (-1,0),  0.5, NAVY),
    ("GRID",          (0,0), (-1,-1), 0.25, LGRAY),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, colors.HexColor("#F9F9FB")]),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(val_t)
story.append(sp())
blended_paras = [
    Paragraph("<b>MSTR BLENDED ~$270</b>    RANGE $177–$450    +52% vs. current ~$177", sMono),
    Paragraph("STRC BLENDED $100    RANGE $95–$105    Yield-driven; price deviation is entry/exit signal", sMono),
]
story.append(colored_block(blended_paras, C_BLEND))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# SCENARIOS
# ════════════════════════════════════════════════════════════════════════════
story.append(section("SCENARIOS — 20% BEAR / 50% BASE / 30% BULL"))

def scenario_table(label, color, prob, description, rows):
    hdr_style = S(f"SHdr{label}", fontName="Arial-Bold", fontSize=9.5,
                   textColor=BLACK)
    desc_style = S(f"SDesc{label}", fontSize=8.5, textColor=GRAY)
    header_cell = [Paragraph(f"<b>{label} ({prob})</b>", hdr_style),
                   Paragraph(description, desc_style)]
    data = [header_cell]
    for timeframe, btc, mstr, strc in rows:
        data.append([
            Paragraph(timeframe, sTD),
            Paragraph(f"BTC {btc}", sTD),
            Paragraph(f"MSTR {mstr}", sTD),
            Paragraph(f"STRC {strc}", sTD),
        ])
    # First row spans all columns
    t = Table(
        [[Paragraph(f"<b>{label} ({prob})</b>  —  {description}", hdr_style)]] +
        [[Paragraph(tf, sTD), Paragraph(f"BTC {b}", sTD),
          Paragraph(f"MSTR {m}", sTD), Paragraph(f"STRC {s}", sTD)]
         for tf, b, m, s in rows],
        colWidths=[0.7*inch, 1.77*inch, 1.77*inch, 1.76*inch]
    )
    style = [
        ("SPAN",          (0,0), (-1,0)),
        ("BACKGROUND",    (0,0), (-1,0),  color),
        ("BACKGROUND",    (0,1), (-1,-1), color),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#CCCCCC")),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]
    t.setStyle(TableStyle(style))
    return t

story.append(scenario_table("BEAR", C_BEAR, "20%",
    "BTC breaks $60k; mNAV compresses to 0.9x; STRC coverage under pressure",
    [("1M", "$75k",  "$120", "$97"),
     ("3M", "$65k",  "$90",  "$94"),
     ("6M", "$58k",  "$70",  "$88"),
     ("1Y", "$55k",  "$55",  "$82")]))
story.append(sp(4))

story.append(scenario_table("BASE", C_BASE, "50%",
    "BTC holds $95k–$110k; mNAV stable 1.2x–1.5x; STRC clips 11.5%",
    [("1M", "$102k", "$195", "$100"),
     ("3M", "$108k", "$220", "$100"),
     ("6M", "$115k", "$260", "$100"),
     ("1Y", "$120k", "$300", "$100")]))
story.append(sp(4))

story.append(scenario_table("BULL", C_BULL, "30%",
    "BTC recovers to $150k+; mNAV re-expands to 2.0x+",
    [("1M", "$115k", "$250", "$100"),
     ("3M", "$135k", "$340", "$100"),
     ("6M", "$150k", "$430", "$100"),
     ("1Y", "$180k", "$600", "$100")]))
story.append(sp(4))

story.append(colored_block([
    Paragraph("<b>BLENDED FV:</b> 1M MSTR ~$220 / STRC ~$100   —   "
              "3M MSTR ~$250 / STRC ~$100", sMono)
], C_BLEND))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# SENSITIVITY
# ════════════════════════════════════════════════════════════════════════════
story.append(section("SENSITIVITY"))
sensitivities = [
    ("BTC ±10%",                    "MSTR ±18%–35% (variable beta 1.8x–3.5x)"),
    ("mNAV expansion +0.5x turn",         "MSTR +40%+ at current BTC price"),
    ("BTC breaks $60k",                   "STRC coverage risk; preferred at discount to par"),
    ("USD reserve drawdown rate rises",    "STRC yield adjustment trigger, monitor monthly"),
    ("Convertible debt maturity",          "MSTR dilution; BTC/share metric resets downward"),
]
sens_data = [[Paragraph(k, sTH), Paragraph(v, sTD)] for k,v in sensitivities]
sens_t = Table(sens_data, colWidths=[2.4*inch, 3.6*inch])
sens_t.setStyle(TableStyle([
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [WHITE, colors.HexColor("#F9F9FB")]),
    ("GRID",          (0,0), (-1,-1), 0.25, LGRAY),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(sens_t)
story.append(PageBreak())

# ════════════════════════════════════════════════════════════════════════════
# TRADES
# ════════════════════════════════════════════════════════════════════════════
story.append(section("TRADES"))

story.append(trade_row(
    "OPTIONS CONTEXT",
    "<b>MSTR:</b> IV rank ~43rd pct [RECENT — AlphaQuery] · 30d IV ~88% (single source) · "
    "Call/put skew: [UNFOUND — check optioncharts.io/options/MSTR/volatility-skew] · 25Δ RR: [UNFOUND]<br/>"
    "<b>BTC:</b> Perp funding rate [UNFOUND — check coinglass.com/FundingRate/BTC] · "
    "On-chain MVRV 1.37 mid-cycle [AhaSignals 2026]<br/>"
    "<b>STRC:</b> No listed options. Income instrument only."
))
story.append(sp(2))

story.append(trade_row(
    "ENTRY VEHICLE",
    "<b>MSTR:</b> Outright — IV at 43rd pct neutral zone; skew [UNFOUND] defaults to outright; "
    "no options edge confirmed. Use spread if IV re-checks above 70th pct before entry.<br/>"
    "<b>BTC:</b> Outright spot/IBIT — perp funding [UNFOUND]; avoid funding drag until confirmed &lt;0.05% 8hr.<br/>"
    "<b>STRC:</b> No options available — outright hold for yield only."
))
story.append(sp(2))

story.append(trade_row(
    "RV TRADE",
    "<i>(Conditional — do not execute until skew confirmed)</i><br/>"
    "Sell COIN [~strike/expiry TBD] call / Buy MSTR [~strike/expiry TBD] call<br/>"
    "Entry condition: confirm MSTR vs. COIN call skew differential &gt;3–5pp via optioncharts.io<br/>"
    "Exit: differential compresses to &lt;1pp"
))
story.append(sp(2))

story.append(trade_row(
    "CORE",
    "<b>Tranche A</b> — Long BTC (spot/IBIT) · entry ~$99,887 · "
    "TP $130,000 (+30%) · SL $75,000 (structural break, −25%)<br/>"
    "<b>Tranche B</b> — Long MSTR · entry $170–$185 · "
    "TP $270 (blended FV, +52%) / $374 (consensus, +111%) · SL $130 (sub-NAV breach, −27%)<br/>"
    "<b>Tranche C</b> — Long STRC · entry at or below $100 par · "
    "hold for 11.5% yield · SL $94 (coverage stress signal, −6%)"
))
story.append(sp(2))

story.append(trade_row(
    "EVENT",
    "MSTR next BTC purchase ~June 2026 — add on confirmation if mNAV re-expanding above 1.3x<br/>"
    "STRC monthly dividend payment — reinvest at par if trading below $99.50"
))
story.append(sp(2))

story.append(trade_row(
    "HEDGE",
    "Short IBIT / Long MSTR — beta-adjusted ratio (~0.3x IBIT short per 1x MSTR long) "
    "if pure mNAV premium-expansion play; cover hedge if BTC sustains &gt;$115k"
))
story.append(sp(2))

story.append(trade_row(
    "ON-CHAIN",
    "BTC-PERP: Enter if funding rate confirmed &lt;0.05% 8hr (coinglass.com/FundingRate/BTC)<br/>"
    "MVRV Z-Score: Enter/add if &lt;0.2; reduce if &gt;2.0 (AhaSignals / MacroMicro)"
))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# SIZING
# ════════════════════════════════════════════════════════════════════════════
story.append(section("SIZING"))
sizing_data = [
    [Paragraph("TRANCHE", sTH), Paragraph("ALLOCATION", sTH),
     Paragraph("RATIONALE", sTH)],
    [Paragraph("A — BTC (spot/IBIT)", sTD),
     Paragraph("3–5% book", sTD),
     Paragraph("Pure directional, most liquid exit, maximum convexity", sTD)],
    [Paragraph("B — MSTR", sTD),
     Paragraph("2–3% book", sTD),
     Paragraph("Size for mNAV re-expansion thesis, accept binary risk vs. BTC", sTD)],
    [Paragraph("C — STRC", sTD),
     Paragraph("2–4% book", sTD),
     Paragraph("Income tranche, size for yield contribution, not capital gains", sTD)],
]
sizing_t = Table(sizing_data, colWidths=[1.8*inch, 1.3*inch, 2.9*inch])
sizing_t.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0),  C_HDR),
    ("LINEBELOW",     (0,0), (-1,0),  0.5, NAVY),
    ("GRID",          (0,0), (-1,-1), 0.25, LGRAY),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, colors.HexColor("#F9F9FB")]),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(sizing_t)
story.append(sp())
story.append(colored_block([
    Paragraph(
        "<b>MAX 10% NAV</b> total BTC-complex exposure  —  "
        "<b>EXP RETURN (blended base/bull):</b> 35–55% over 12 months  —  "
        "<b>MAX DD:</b> −30% Tranche A · −35% Tranche B · −10% Tranche C",
        sMono)
], C_HDR))
story.append(sp(10))

# ════════════════════════════════════════════════════════════════════════════
# TIME-SENSITIVE FLAGS
# ════════════════════════════════════════════════════════════════════════════
story.append(section("TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS"))

flags = [
    ("BTC PRICE CONFLICT",
     "Fortune (May 15 2026) reported $80,120; more recent sources indicate ~$99,887. "
     "Confirm at coinbase.com or coinglass.com before entry. All scenario prices use $99,887 as base."),
    ("MSTR IV RANK",
     "Single source (AlphaQuery, ~43rd pct). Verify at marketchameleon.com/Stock/MSTR/Options "
     "or barchart.com/stocks/quotes/MSTR/options before trading."),
    ("MSTR CALL/PUT SKEW",
     "[UNFOUND]. Searched flashalpha.com, optioncharts.io, marketbeat.com — no 25Δ RR value returned. "
     "Check optioncharts.io/options/MSTR/volatility-skew before confirming ENTRY VEHICLE. "
     "If call skew bid &gt;5pp vs. COIN, RV trade is live; if &gt;70th pct IV, use spread not outright."),
    ("BTC PERP FUNDING RATE",
     "[UNFOUND]. CoinGlass platform confirmed but no live rate extracted. "
     "Check coinglass.com/FundingRate/BTC — if &gt;0.10% 8hr, avoid perp; use spot/IBIT only."),
    ("RV TRADE EXECUTION",
     "Do not execute COIN/MSTR skew trade until differential confirmed &gt;3–5pp. "
     "Skew data needed from optioncharts.io before sizing."),
    ("MSTR SHORT INTEREST BASIS",
     "11.31% short float is predominantly basis trades (long IBIT / short MSTR — "
     "CoinDesk Feb 2026, Jane Street confirmed). Not outright bearish. "
     "Monitor if BTC sustains &gt;$120k for potential basis unwind squeeze."),
    ("STRC DIVIDEND COVERAGE",
     "$2.25B reserves = 21.8 months. Monitor monthly announcements. "
     "Flag if drawdown rate accelerates or reserve falls below 12 months."),
    ("OPTIONS DATA SOURCE",
     "MSTR options data searched but limited to single or dated sources. "
     "All options data labeled [RECENT] or [UNFOUND] per confidence tier protocol. "
     "No options data fabricated."),
]

flag_data = [
    [Paragraph(f"<b>{k}</b>", sFlag), Paragraph(v, sFlag)]
    for k, v in flags
]
flag_t = Table(flag_data, colWidths=[1.7*inch, 4.3*inch])
flag_t.setStyle(TableStyle([
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#FFF8F8"), WHITE]),
    ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#FFCCCC")),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
]))
story.append(flag_t)

# ════════════════════════════════════════════════════════════════════════════
# BUILD PDF
# ════════════════════════════════════════════════════════════════════════════
OUTPUT = r"C:\Users\matth\OneDrive\Documents\Claude\Code\btc-mstr-strc-deep-dive-2026-05-19.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    leftMargin=LM, rightMargin=RM,
    topMargin=TM, bottomMargin=BM,
    title="Strategy Capital Stack — BTC/MSTR/STRC Deep Dive",
    author="FOR FRENS AND FAMILIE ONLY",
)

doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f"PDF saved: {OUTPUT}")
