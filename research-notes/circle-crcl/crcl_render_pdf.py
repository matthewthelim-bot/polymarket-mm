"""
CRCL Deep Dive — Professional Buy-Side Research Note PDF
Uses reportlab Platypus for multi-page, styled output.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor, black, white
import os

# ── Output path ───────────────────────────────────────────────────────────────
OUT_PATH   = r"C:\Users\matth\OneDrive\Documents\Claude\Code\CRCL_Deep_Dive_May2026.pdf"
CHART1     = r"C:\Users\matth\OneDrive\Documents\Claude\Code\crcl_chart1_revenue_ebitda.png"
CHART2     = r"C:\Users\matth\OneDrive\Documents\Claude\Code\crcl_chart2_valuation.png"

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY       = HexColor('#1B3A6B')
NAVY_LT    = HexColor('#2F5F9E')
AMBER      = HexColor('#C8811A')
GREY_BG    = HexColor('#F7F7F7')
GREY_RULE  = HexColor('#CBD5E0')
CALLOUT_BG = HexColor('#F0F4FA')
CALLOUT_BD = HexColor('#BFD0E8')
RED_FLAG   = HexColor('#FFF5F0')
RED_BD     = HexColor('#F4A582')
TXT_DARK   = HexColor('#1A202C')
TXT_MID    = HexColor('#4A5568')
TXT_LIGHT  = HexColor('#8C9BB0')

PAGE_W, PAGE_H = letter
L_MAR = R_MAR = 1.25 * inch
T_MAR = B_MAR = 1.0 * inch
BODY_W = PAGE_W - L_MAR - R_MAR

# ── Header / Footer ───────────────────────────────────────────────────────────
HDR_TXT = "SINGLE-STOCK  ·  CRCL  ·  MAY 13, 2026  ·  INTERNAL / BUY-SIDE ONLY"
FTR_TXT = "Internal research note — not for distribution.  MAY 13, 2026."

def on_page(canvas, doc):
    canvas.saveState()
    # Header rule
    canvas.setStrokeColor(NAVY)
    canvas.setLineWidth(0.5)
    canvas.line(L_MAR, PAGE_H - T_MAR + 14, PAGE_W - R_MAR, PAGE_H - T_MAR + 14)
    # Header text
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TXT_MID)
    canvas.drawRightString(PAGE_W - R_MAR, PAGE_H - T_MAR + 18, HDR_TXT)
    # Footer rule
    canvas.line(L_MAR, B_MAR - 8, PAGE_W - R_MAR, B_MAR - 8)
    # Footer text
    canvas.drawCentredString(PAGE_W / 2, B_MAR - 20, FTR_TXT)
    # Page number
    canvas.drawRightString(PAGE_W - R_MAR, B_MAR - 20, f"Page {doc.page}")
    canvas.restoreState()

def on_first_page(canvas, doc):
    on_page(canvas, doc)

# ── Styles ────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def sty(name, parent='Normal', **kw):
    s = ParagraphStyle(name, parent=base[parent])
    for k, v in kw.items():
        setattr(s, k, v)
    return s

S_BODY      = sty('body',      fontName='Helvetica',      fontSize=10,   leading=15,   textColor=TXT_DARK, alignment=TA_JUSTIFY, spaceAfter=6)
S_BODY_SM   = sty('body_sm',   fontName='Helvetica',      fontSize=8.5,  leading=13,   textColor=TXT_MID,  alignment=TA_LEFT,    spaceAfter=4)
S_BOLD      = sty('bold',      fontName='Helvetica-Bold', fontSize=10,   leading=15,   textColor=TXT_DARK)
S_LABEL     = sty('label',     fontName='Helvetica-Bold', fontSize=8,    leading=11,   textColor=NAVY,     spaceAfter=2)
S_NOTE      = sty('note',      fontName='Helvetica-Oblique', fontSize=8, leading=12,   textColor=TXT_LIGHT, spaceAfter=4)
S_FOOTNOTE  = sty('fnote',     fontName='Helvetica',      fontSize=8,    leading=12,   textColor=TXT_MID,  spaceAfter=3)

# Section header
S_SEC = sty('section', fontName='Helvetica-Bold', fontSize=12.5, leading=18,
            textColor=NAVY, spaceBefore=18, spaceAfter=6,
            borderPad=0)

# Sub-header
S_SUB = sty('sub', fontName='Helvetica-Bold', fontSize=10.5, leading=15,
            textColor=NAVY_LT, spaceBefore=10, spaceAfter=4)

# Cover title
S_COVER_BADGE = sty('badge',  fontName='Helvetica',      fontSize=8,    leading=11,   textColor=white,    alignment=TA_CENTER)
S_COVER_TITLE = sty('ctitle', fontName='Helvetica-Bold', fontSize=22,   leading=28,   textColor=NAVY,     spaceBefore=8, spaceAfter=6)
S_COVER_SUB   = sty('csub',   fontName='Helvetica',      fontSize=11,   leading=17,   textColor=TXT_DARK, alignment=TA_LEFT, spaceAfter=12)

# Table header / cell
S_TH  = sty('th',  fontName='Helvetica-Bold', fontSize=8.5,  leading=12, textColor=white,    alignment=TA_LEFT)
S_TD  = sty('td',  fontName='Helvetica',      fontSize=8.5,  leading=12, textColor=TXT_DARK, alignment=TA_LEFT)
S_TD2 = sty('td2', fontName='Helvetica',      fontSize=8,    leading=12, textColor=TXT_MID,  alignment=TA_LEFT)

# Monitor / bullet
S_BULLET = sty('bullet', fontName='Helvetica', fontSize=9.5, leading=14, textColor=TXT_DARK,
               leftIndent=10, firstLineIndent=-10, spaceAfter=5)
S_MONITOR = sty('monitor', fontName='Helvetica', fontSize=9.5, leading=14, textColor=TXT_DARK,
                leftIndent=0, spaceAfter=6)

# ── Callout box flowable ───────────────────────────────────────────────────────
class CalloutBox(Flowable):
    def __init__(self, content, bg=CALLOUT_BG, border=CALLOUT_BD, label=None, label_color=NAVY):
        super().__init__()
        self.content = content   # list of Paragraph
        self.bg = bg
        self.border = border
        self.label = label
        self.label_color = label_color
        self._width = BODY_W
        self._height = None

    def wrap(self, avail_w, avail_h):
        # measure content
        inner_w = self._width - 24
        total_h = 12  # padding top
        if self.label:
            total_h += 14
        for p in self.content:
            w, h = p.wrap(inner_w, avail_h)
            total_h += h + 4
        total_h += 10  # padding bottom
        self._height = total_h
        return (self._width, self._height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.bg)
        c.setStrokeColor(self.border)
        c.setLineWidth(0.8)
        c.roundRect(0, 0, self._width, self._height, 4, fill=1, stroke=1)
        # left accent bar
        c.setFillColor(self.border)
        c.rect(0, 0, 3, self._height, fill=1, stroke=0)

        y = self._height - 12
        if self.label:
            c.setFont("Helvetica-Bold", 7.5)
            c.setFillColor(self.label_color)
            c.drawString(12, y - 10, self.label)
            y -= 16

        inner_w = self._width - 24
        for p in self.content:
            w, h = p.wrap(inner_w, 9999)
            p.drawOn(c, 12, y - h)
            y -= (h + 4)
        c.restoreState()

# ── Helper: horizontal rule ────────────────────────────────────────────────────
def rule(color=GREY_RULE, thickness=0.5):
    return HRFlowable(width='100%', thickness=thickness, color=color,
                      spaceAfter=8, spaceBefore=4)

# ── Helper: section header ────────────────────────────────────────────────────
def sec(text):
    return [
        rule(NAVY, 1.0),
        Paragraph(text, S_SEC),
    ]

# ── Helper: ticker bold ────────────────────────────────────────────────────────
def b(text):
    return f'<b>{text}</b>'

# ── Helper: table ─────────────────────────────────────────────────────────────
def make_table(header, rows, col_widths=None):
    data = [[Paragraph(h, S_TH) for h in header]]
    for i, row in enumerate(rows):
        style = S_TD if i % 2 == 0 else sty(f'td_alt_{i}', fontName='Helvetica',
                                              fontSize=8.5, leading=12,
                                              textColor=TXT_DARK, alignment=TA_LEFT)
        data.append([Paragraph(str(c), style) for c in row])

    if col_widths is None:
        col_widths = [BODY_W / len(header)] * len(header)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0),  NAVY),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8.5),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  7),
        ('TOPPADDING',    (0, 0), (-1, 0),  7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, GREY_BG]),
        ('GRID',          (0, 0), (-1, -1), 0.5, GREY_RULE),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 7),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 7),
    ]
    t.setStyle(TableStyle(style_cmds))
    return t

# ── Helper: chart embed ────────────────────────────────────────────────────────
def chart_img(path, caption=None):
    items = []
    if os.path.exists(path):
        img = Image(path, width=BODY_W, height=BODY_W * 0.56)
        items.append(Spacer(1, 8))
        items.append(img)
        if caption:
            items.append(Paragraph(caption, S_NOTE))
        items.append(Spacer(1, 8))
    else:
        items.append(Paragraph(f'[Chart not found: {path}]', S_NOTE))
    return items

# ── Build story ───────────────────────────────────────────────────────────────
story = []

# ─── COVER BLOCK ─────────────────────────────────────────────────────────────
# Badge
badge_data = [["SINGLE-STOCK  ·  INTERNAL / BUY-SIDE ONLY  ·  MAY 13, 2026"]]
badge_tbl = Table(badge_data, colWidths=[BODY_W])
badge_tbl.setStyle(TableStyle([
    ('BACKGROUND',    (0,0), (-1,-1), NAVY),
    ('TEXTCOLOR',     (0,0), (-1,-1), white),
    ('FONTNAME',      (0,0), (-1,-1), 'Helvetica-Bold'),
    ('FONTSIZE',      (0,0), (-1,-1), 8),
    ('TOPPADDING',    (0,0), (-1,-1), 7),
    ('BOTTOMPADDING', (0,0), (-1,-1), 7),
    ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
]))
story.append(badge_tbl)
story.append(Spacer(1, 14))

story.append(Paragraph("Circle Internet Group (<b>CRCL</b>)", S_COVER_TITLE))
story.append(Paragraph(
    "The regulated stablecoin infrastructure layer — priced for perfection after a "
    "<b>+68% YTD run</b>, with three unresolved debates that determine whether this "
    "is a <b>$200 stock or a $75 stock</b>.",
    S_COVER_SUB))

# Quick stats bar
stats = [
    ["NYSE: CRCL", "Price: ~$123", "Mkt Cap: ~$30.5B", "IPO: Jun 5, 2025", "YTD: +68%"]
]
stats_tbl = Table(stats, colWidths=[BODY_W/5]*5)
stats_tbl.setStyle(TableStyle([
    ('BACKGROUND',    (0,0), (-1,-1), CALLOUT_BG),
    ('TEXTCOLOR',     (0,0), (-1,-1), NAVY),
    ('FONTNAME',      (0,0), (-1,-1), 'Helvetica-Bold'),
    ('FONTSIZE',      (0,0), (-1,-1), 9),
    ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
    ('TOPPADDING',    (0,0), (-1,-1), 8),
    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ('GRID',          (0,0), (-1,-1), 0.5, CALLOUT_BD),
    ('BOX',           (0,0), (-1,-1), 1.0, NAVY),
]))
story.append(stats_tbl)
story.append(Spacer(1, 6))
story.append(rule(NAVY, 1.5))

# ─── 01 — BUSINESS FRAME ─────────────────────────────────────────────────────
story += sec("01 — BUSINESS FRAME")

story.append(Paragraph(
    "Circle is the issuer of <b>USDC</b>, the second-largest stablecoin by supply and "
    "now the #1 stablecoin by adjusted on-chain transaction volume. The business model "
    "is structurally simple: Circle earns yield on the short-term Treasury and money "
    "market reserves backing every USDC in circulation. USDC in circulation stood at "
    "<b>$77.0B</b> at Q1 2026 end, up 28% YoY, with on-chain transaction volume of "
    "<b>$21.5T</b>, up 263% YoY.", S_BODY))

story.append(Paragraph(
    "Revenue is not diversified: reserve income represented $2,637M of FY2025 total "
    "revenue and reserve income of $2,750M, with \"other revenue\" (API services, "
    "Circle Payments Network, enterprise) contributing ~$90–100M — guided to "
    "$150–170M in FY2026, the company's primary non-rate-linked growth vector.", S_BODY))

story.append(Paragraph(
    "<b>TAM framing</b>: USDC + Tether control >99% of on-chain stablecoin transaction "
    "volume. The stablecoin supply market is currently ~$240B globally; institutional "
    "projections put the 5-year TAM at $1–2T if regulatory frameworks hold.", S_BODY))

# ─── 02 — COMPETITIVE POSITION ────────────────────────────────────────────────
story += sec("02 — COMPETITIVE POSITION")

story.append(Paragraph("THE MOAT", S_SUB))
story.append(Paragraph(
    "<b>USDC is a regulatory-first, compliance-native stablecoin — the only one "
    "positioned to absorb institutional and sovereign-grade demand under the GENIUS "
    "Act regime.</b> Evidence of durability:", S_BODY))

moat_items = [
    ("<b>Transaction volume dominance</b>",
     "USDC adjusted transaction volume of $2.2T YTD 2026 vs. Tether's $1.3T — "
     "USDC now commands ~64% of adjusted stablecoin volume (CoinDesk, May 2026). "
     "This is a structural share gain, not a crypto-price artifact."),
    ("<b>Reserve credibility</b>",
     "Circle has maintained Treasury-heavy reserves since 2023 — precisely the "
     "composition the GENIUS Act (signed July 18, 2025) mandates as the compliance "
     "standard. New entrants must restructure to comply; USDC is already there."),
    ("<b>Network effects</b>",
     "USDC is integrated across every major DeFi protocol, exchange, and payment "
     "platform. Switching costs are low at the individual level but enormous at the "
     "ecosystem level — every protocol pricing in USDC liquidity creates a friction "
     "point for displacement."),
    ("<b>Institutional validation</b>",
     "Arc token presale (May 2026, $222M at $3B valuation) attracted <b>BlackRock</b>, "
     "<b>Apollo</b>, <b>a16z</b>, <b>ICE</b>, and <b>ARK</b> — this is not retail "
     "validation. These names do diligence. (CNBC, May 11, 2026)"),
]
for i, (head, body) in enumerate(moat_items, 1):
    story.append(Paragraph(f"{i}. {head}: {body}", S_BODY))

story.append(Spacer(1, 4))
story.append(Paragraph("THREATS (NAMED)", S_SUB))

threats = [
    ("<b>Coinbase structural drag (existential risk at scale)</b>",
     "<b>COIN</b> earned ~56% of USDC reserve revenue in FY2024 under a "
     "revenue-sharing agreement giving Coinbase 100% of interest on USDC held "
     "directly on Coinbase, and 50% on all off-platform USDC. Coinbase's share of "
     "USDC supply has grown: 5% (2022) → 12% (2023) → 20% (2024) → 22% (Q1 2025). "
     "Agreement renews in 2026. <b>This is the single most important number to track.</b>"),
    ("<b>Bank-issued stablecoins (medium-term structural)</b>",
     "The GENIUS Act enables banks and fintechs to issue their own dollar stablecoins. "
     "JPMorgan, BofA, and payments networks have the distribution infrastructure to "
     "challenge USDC. Timeline to meaningful supply: 2–4 years. Risk is real; urgency "
     "is not acute in a 12-month horizon."),
    ("<b>Interest rate compression (immediate, quantifiable)</b>",
     "Each 25bps Fed rate cut reduces reserve income by approximately <b>$50–70M</b> "
     "at current USDC supply levels. The Fed's rate path is the single biggest "
     "external variable for Circle's P&L."),
]
for i, (head, body) in enumerate(threats, 1):
    story.append(Paragraph(f"{i}. {head}: {body}", S_BODY))

# ─── 03 — FINANCIALS ──────────────────────────────────────────────────────────
story += sec("03 — FINANCIALS")

fin_header = ["METRIC", "FY2024A", "FY2025A", "FY2026E"]
fin_rows = [
    ["Total Revenue & Reserve Income", "$1.70B", "$2.75B", "~$2.80–3.00B"],
    ["YoY Growth", "—", "+64%", "+2–9%"],
    ["RLDC Margin", "~39%", "39.4%", "38–40% (guided)"],
    ["Adj. EBITDA", "~$112M¹", "$582M", "~$634M"],
    ["Net Income / (Loss)", "$155.7M", "($69.5M)²", "~$55M³"],
    ["Other Revenue", "—", "~$95M", "$150–170M"],
]
fin_cw = [BODY_W*0.38, BODY_W*0.20, BODY_W*0.20, BODY_W*0.22]
story.append(make_table(fin_header, fin_rows, fin_cw))
story.append(Spacer(1, 4))

for fn in [
    "¹ Directional estimate — FY2024 Adj. EBITDA not separately confirmed.",
    "² Distorted by $424M stock-based compensation triggered by IPO vesting conditions.",
    "³ Q1 2026 net income from continuing operations was $55M; full-year consensus not confirmed.",
]:
    story.append(Paragraph(fn, S_FOOTNOTE))

callout1 = CalloutBox(
    [Paragraph("<b>Key structural note</b>: RLDC margin (the yield Circle retains after "
               "paying distribution costs to <b>COIN</b> and other partners) is the most "
               "important profitability metric. The 38–40% guided range implies Coinbase "
               "receives ~60–62% of gross reserve income on USDC it touches — effectively "
               "making Coinbase the silent majority owner of Circle's economics.", S_BODY),
     Paragraph("Balance sheet: Net cash position not confirmed. Adj. OpEx guided to "
               "$570–585M in FY2026. FCF data not available in public filings — [UNFOUND].", S_BODY_SM)],
    label="STRUCTURAL NOTE"
)
story.append(Spacer(1, 4))
story.append(callout1)

# Chart 1
story += chart_img(CHART1, "Fig. 1 — CRCL Revenue & Adj. EBITDA Trend. "
                   "Source: Circle earnings releases, analyst estimates. FY2024 EBITDA is a directional estimate.")

# ─── 04 — VALUATION ──────────────────────────────────────────────────────────
story += sec("04 — VALUATION")

val_header = ["MULTIPLE", "CRCL (current)", "Peer Avg (directional)", "NOTE"]
val_rows = [
    ["NTM EV/EBITDA", "43.4x", "~18–25x",
     "Growth premium; defensible only if Arc & USDC compound at >20%"],
    ["NTM P/E", "99.8x", "~22–30x",
     "Normalized EPS falling 49% FY2025→FY2026 as Arc spend peaks"],
    ["Trailing P/E", "NM (loss)", "—", "$424M SBC distorts FY2025"],
]
val_cw = [BODY_W*0.20, BODY_W*0.18, BODY_W*0.22, BODY_W*0.40]
story.append(make_table(val_header, val_rows, val_cw))
story.append(Spacer(1, 6))
story.append(Paragraph(
    "<i>Peer set (directional estimate)</i>: No clean comp exists for <b>CRCL</b>. "
    "Fintech infrastructure (<b>TW</b>, <b>SQ</b>) and crypto proxies (<b>COIN</b>) "
    "blended. <b>Bull at $280</b> (Seaport Global): USDC reaches $200B+, Arc becomes "
    "a leading institutional blockchain, and Circle renegotiates the Coinbase revenue "
    "share. <b>Bear at $77–80</b> (Compass Point, Morgan Stanley): Fed cuts 100bps+, "
    "Coinbase dependency worsens, Arc execution disappoints.", S_BODY_SM))

# Chart 2
story += chart_img(CHART2, "Fig. 2 — CRCL NTM EV/EBITDA and P/E vs. peer group. "
                   "Source: Analyst estimates, Yahoo Finance (May 2026). Peer multiples are directional estimates.")

# ─── 05 — THE DEBATE ─────────────────────────────────────────────────────────
story += sec("05 — THE DEBATE")

bull_box = CalloutBox(
    [Paragraph("<b>BULL CASE</b>", S_LABEL),
     Paragraph(
         "Circle is the only regulated, institutionally credible stablecoin issuer at "
         "scale. USDC's transaction volume now exceeds Tether's despite lower supply — "
         "the velocity leader, not just the compliance-friendly option. The GENIUS Act "
         "created a regulatory moat that excludes non-compliant issuers and raises the "
         "barrier for new bank entrants by meaningful years. The Arc raise "
         "(<b>BlackRock</b>, <b>a16z</b>, <b>Apollo</b>) signals the 'just a stablecoin "
         "company' narrative is ending. <b>Regulatory clarity + adoption velocity + Arc "
         "optionality = a once-in-a-decade infrastructure bet at the intersection of AI, "
         "fintech, and cross-border settlement.</b> The Q1 2026 EPS beat of 19% above "
         "consensus shows operating leverage is real even as investments peak.", S_BODY)],
    bg=HexColor('#F0F7F0'), border=HexColor('#6DB896'), label_color=HexColor('#276749')
)
story.append(bull_box)
story.append(Spacer(1, 8))

bear_box = CalloutBox(
    [Paragraph("<b>BEAR CASE</b>", S_LABEL),
     Paragraph(
         "The Coinbase dependency is a fatal structural flaw that worsens with each "
         "quarter. <b>COIN</b> earned 56% of Circle's reserve revenue in FY2024 — a "
         "revenue share arrangement that <b>CRCL</b> had no leverage to renegotiate "
         "when it IPO'd. As Coinbase grows its USDC distribution share (5% → 22% in "
         "three years), Circle's effective yield per USDC in circulation declines "
         "structurally. The stock trades at 43x NTM EBITDA after a 68% YTD run, with "
         "EPS projected to fall 49% YoY as Arc investments peak. The GENIUS Act tailwind "
         "is fully priced: <b>CRCL</b> surged 20% on the May 4 CLARITY Act headline — "
         "completed catalyst, not pending. The Q1 2026 revenue miss (EPS beat on cost "
         "discipline, not revenue strength) is the canary. <b>If the Fed cuts 100bps, "
         "the stock is a $75–85 print.</b>", S_BODY)],
    bg=RED_FLAG, border=RED_BD, label_color=HexColor('#C53030')
)
story.append(bear_box)
story.append(Spacer(1, 8))

view_box = CalloutBox(
    [Paragraph("<b>VIEW</b>", S_LABEL),
     Paragraph(
         "The business is exceptional. The stock, after 68% YTD, is not. The Coinbase "
         "structural drag is underappreciated by consensus, and the revenue miss in "
         "Q1 2026 is the first sign that growth assumptions are being stress-tested. "
         "Arc is an asymmetric bet, but it adds execution risk and is 12–24 months "
         "from generating meaningful revenue. <b>The risk/reward for new money at $123 "
         "is unattractive. For existing holders: hold with active stops on Fed rate cut "
         "catalysts and Coinbase revenue share renegotiation outcomes.</b>", S_BODY)],
    label="RECOMMENDATION"
)
story.append(view_box)

# ─── 06 — POSITIONING ─────────────────────────────────────────────────────────
story += sec("06 — POSITIONING")

story.append(Paragraph(
    "<b>Short interest</b>: [UNFOUND] — GuruFocus license change eliminated this "
    "data stream. Check S3 Partners or Ortex before sizing any position.", S_BODY))
story.append(Paragraph(
    "<b>Institutional ownership</b>: 475 institutions holding ~105.8M shares. "
    "Largest holders: Marshall Wace, IDG-Accel, a16z (Accel XI Associates), "
    "Susquehanna International Group, <b>BlackRock</b>, Vanguard, <b>ARK</b>, "
    "Citadel. (Fintel, most recent 13F)", S_BODY))
story.append(Paragraph(
    "<i>Directional estimate</i>: Early-to-mid institutional consensus — not crowded "
    "in the traditional sense. The May 11 Arc presale added <b>BlackRock</b> and "
    "<b>Apollo</b> as direct economic stakeholders. ARK's presence signals "
    "high-conviction growth positioning. However, the 68% YTD run will have triggered "
    "momentum flows; any reversal will find fast-money positions unwound quickly.", S_BODY))

# ─── 07 — TRADEABLE EXPRESSION ────────────────────────────────────────────────
story += sec("07 — TRADEABLE EXPRESSION")
story.append(Paragraph("CATALYST CALENDAR", S_SUB))

catalysts = [
    ("(1)", "Coinbase revenue share renegotiation — due 2026 (exact date unconfirmed). Outcome is binary: improved terms = structural re-rating; renewed on current terms = persistent multiple cap."),
    ("(2)", "Arc blockchain mainnet launch — targeted H2 2026. First institutional transaction volume data will reprice the optionality embedded in current multiple."),
    ("(3)", "Q2 2026 earnings — estimated ~August 2026. Watch USDC circulation trajectory and whether Q1 revenue miss was a temporary glitch or trend."),
    ("(4)", "Federal Reserve rate decisions — any 25bps cut = ~$50–70M annual reserve income headwind at current supply levels."),
    ("(5)", "GENIUS Act compliance deadline — July 18, 2026. Non-compliant issuers must restructure; potential market share acceleration to USDC if competitors stumble."),
]
for num, txt in catalysts:
    story.append(Paragraph(f"<b>{num}</b>  {txt}", S_BULLET))

story.append(Spacer(1, 6))
story.append(Paragraph("EXPRESSION", S_SUB))

expr_box = CalloutBox(
    [Paragraph("<b>Hold existing positions. Do not add new money at current price (~$123).</b>", S_BODY),
     Paragraph("Ideal entry for new money: <b>$90–105 range</b> (~15–25% discount; arrives "
               "on rate cut signal, Q2 miss, or Arc execution concern).", S_BODY),
     Paragraph("Pre-Arc sizing: <b>3% of book</b> at $90–105. Add to <b>5–6%</b> on Arc "
               "mainnet confirmation with institutional volume metrics above $1B/quarter.", S_BODY),
     Paragraph("Hedge: Long <b>SHY</b> (3-month Treasury ETF) as rate hedge. Alternatively, "
               "small <b>COIN</b> long captures Coinbase renegotiation upside — <b>COIN</b> "
               "benefits from the same tailwind <b>CRCL</b> loses if arrangement holds.", S_BODY),
     Paragraph("Exit: Close/reduce if (a) Coinbase USDC share >30% without renegotiation, "
               "(b) USDC supply growth <15% YoY for two consecutive quarters, "
               "or (c) Fed cuts >75bps without offsetting USDC growth.", S_BODY),
     Paragraph("Time horizon: <b>12–18 months</b>.", S_BODY)],
    label="TRADE STRUCTURE"
)
story.append(expr_box)

# ─── 08 — WHAT TO MONITOR ─────────────────────────────────────────────────────
story += sec("08 — WHAT TO MONITOR")

monitors = [
    ("USDC SUPPLY WEEKLY",
     "circle.com/transparency — published weekly. Threshold: $90B = reaccelerating adoption; below $70B = structural problem."),
    ("COINBASE REVENUE SHARE",
     "COIN and CRCL 10-Qs: 'distribution, transaction and other costs' line. If this grows faster than USDC supply, economics are deteriorating. Watch for 8-K on renegotiation terms."),
    ("FED RATE DECISIONS",
     "FOMC 2026: Jun 18, Jul 30, Sep 17, Nov 5, Dec 17. Each 25bps cut = ~$50–70M annual headwind. Break-even: USDC supply must grow ~$5–7B per 25bps cut."),
    ("ARC MAINNET METRICS",
     "First institutional settlement volume, TVL vs. Ethereum/Solana, ARC token exchange listing. Mainnet without institutional uptake = optionality collapses."),
    ("Q2 2026 EARNINGS (~AUGUST)",
     "Key metric: other revenue vs. $150–170M annualized guide. Second miss confirms deceleration."),
    ("GENIUS ACT DEADLINE (JUL 18)",
     "Tether compliance or non-compliance. If Tether is restricted from US markets, USDC supply could surge materially."),
    ("BANK STABLECOIN ISSUANCE",
     "OCC and Fed approvals for bank-chartered stablecoin issuers. Any JPMorgan or BofA announcement changes the long-term TAM argument."),
]

monitor_data = [[Paragraph(f"<b>{label}</b>", S_TD), Paragraph(desc, S_TD)]
                for label, desc in monitors]
monitor_tbl = Table(monitor_data, colWidths=[BODY_W*0.30, BODY_W*0.70])
monitor_tbl.setStyle(TableStyle([
    ('ROWBACKGROUNDS', (0,0), (-1,-1), [white, GREY_BG]),
    ('GRID',          (0,0), (-1,-1), 0.5, GREY_RULE),
    ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ('TOPPADDING',    (0,0), (-1,-1), 6),
    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ('LEFTPADDING',   (0,0), (-1,-1), 7),
    ('RIGHTPADDING',  (0,0), (-1,-1), 7),
]))
story.append(monitor_tbl)

# ─── TIME-SENSITIVE FLAGS ─────────────────────────────────────────────────────
story += sec("TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS")

flags = [
    ("<b>SHORT INTEREST DATA</b>",
     "Short interest for <b>CRCL</b> is [UNFOUND]. GuruFocus discontinued this dataset. "
     "Check S3 Partners, Ortex, or FINRA short interest reports before sizing any position. "
     "A high short base would add squeeze potential to the Arc mainnet catalyst."),
    ("<b>FCF DATA</b>",
     "Free cash flow is [UNFOUND] from public sources reviewed. Verify FCF conversion from "
     "EBITDA via investor.circle.com before modeling. The $424M SBC charge in FY2025 distorts "
     "net income but does not affect cash generation."),
    ("<b>COINBASE RENEGOTIATION TIMING</b>",
     "The agreement 'renews in 2026' per multiple sources, but the exact date is Single source. "
     "Confirm with Circle's most recent 10-K or 8-K. This is the most important binary catalyst "
     "for Circle's long-term economics."),
    ("<b>FY2024 ADJ. EBITDA</b>",
     "The ~$112M FY2024A Adj. EBITDA figure is a Directional estimate derived from analyst "
     "projections, not confirmed in earnings filings. Verify against circle.com/pressroom."),
    ("<b>PEER VALUATION MULTIPLES</b>",
     "Peer average EV/EBITDA and P/E ranges are Directional estimates. Circle has no clean "
     "comp set. Apply multiples cautiously."),
    ("<b>NORMALIZED EPS FY2026E</b>",
     "The 49% EPS compression ($2.35 → $1.20) is a Directional estimate from one analyst "
     "source. Verify against current consensus at Bloomberg or FactSet before trading."),
]

flag_paras = []
for head, body in flags:
    flag_paras.append(Paragraph(f"•  {head}: {body}", S_BODY))

flag_box = CalloutBox(flag_paras, bg=RED_FLAG, border=RED_BD, label="TIME-SENSITIVE FLAGS")
story.append(flag_box)

story.append(Spacer(1, 16))
story.append(rule(NAVY, 1.0))
story.append(Paragraph(
    "<i>Internal research note — not for distribution. All views represent "
    "forward-looking estimates subject to material revision. Verify all flagged "
    "items before trading. MAY 13, 2026.</i>", S_NOTE))

# ── Build PDF ──────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT_PATH,
    pagesize=letter,
    leftMargin=L_MAR,
    rightMargin=R_MAR,
    topMargin=T_MAR + 0.3 * inch,
    bottomMargin=B_MAR + 0.3 * inch,
    title="Circle Internet Group (CRCL) — Deep Dive",
    author="Buy-Side Research",
    subject="Single-Stock Analysis",
)
doc.build(story, onFirstPage=on_first_page, onLaterPages=on_page)
print(f"PDF saved: {OUT_PATH}")
