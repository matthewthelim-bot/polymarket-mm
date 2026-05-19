from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak, HRFlowable, KeepTogether)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ── Fonts ──────────────────────────────────────────────────────────────────────
FONT_DIR = r"C:\Windows\Fonts"
try:
    pdfmetrics.registerFont(TTFont("Ar",   os.path.join(FONT_DIR, "arial.ttf")))
    pdfmetrics.registerFont(TTFont("ArB",  os.path.join(FONT_DIR, "arialbd.ttf")))
    pdfmetrics.registerFont(TTFont("ArI",  os.path.join(FONT_DIR, "ariali.ttf")))
    pdfmetrics.registerFont(TTFont("ArBI", os.path.join(FONT_DIR, "arialbi.ttf")))
    pdfmetrics.registerFontFamily("Ar", normal="Ar", bold="ArB", italic="ArI", boldItalic="ArBI")
    BF, BB, BI = "Ar", "ArB", "ArI"
except Exception as e:
    print(f"Arial not found ({e}), falling back to Helvetica")
    BF, BB, BI = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

# ── Constants ──────────────────────────────────────────────────────────────────
OUTPUT = r"C:\Users\matth\OneDrive\Documents\Claude\Code\spacex-ipo-proxy-plays-debate-2026-05-18-v2.pdf"
DATE   = "18 May 2026"
BRAND  = "FOR FRENS AND FAMILIE ONLY"
W      = 6.0 * inch   # text block width

NAVY   = colors.HexColor("#1A1A2E")
LGRAY  = colors.HexColor("#F7F7F7")
MGRAY  = colors.HexColor("#CCCCCC")
DGRAY  = colors.HexColor("#555555")
BEAR_C = colors.HexColor("#FFF0F0")
BASE_C = colors.HexColor("#F7F7F7")
BULL_C = colors.HexColor("#F0FFF0")
BLEND_C= colors.HexColor("#F0F0FF")
RED    = colors.HexColor("#C0392B")
GREEN  = colors.HexColor("#27AE60")
CREAM  = colors.HexColor("#FFFEF0")

# ── Styles ─────────────────────────────────────────────────────────────────────
def ps(name, **kw):
    return ParagraphStyle(name, **kw)

cover_title = ps("CoverTitle", fontName=BB, fontSize=26, leading=32, textColor=NAVY, spaceAfter=8)
cover_sub   = ps("CoverSub",   fontName=BF, fontSize=12, leading=16, textColor=DGRAY, spaceAfter=4)
cover_brand = ps("CoverBrand", fontName=BI, fontSize=9,  leading=12, textColor=colors.gray, spaceAfter=2)
cover_label = ps("CoverLabel", fontName=BB, fontSize=11, leading=14, textColor=colors.HexColor("#888888"), spaceAfter=4)
h1  = ps("H1",  fontName=BB, fontSize=13, leading=17, textColor=NAVY, spaceAfter=4, spaceBefore=10)
h2  = ps("H2",  fontName=BB, fontSize=11, leading=14, textColor=NAVY, spaceAfter=3, spaceBefore=8)
h3  = ps("H3",  fontName=BB, fontSize=10, leading=13, textColor=NAVY, spaceAfter=2, spaceBefore=6)
bod = ps("Bod",  fontName=BF, fontSize=9.5, leading=13.5, spaceAfter=4)
sml = ps("Sml",  fontName=BF, fontSize=8.5, leading=12, spaceAfter=3)
sml_i = ps("SmlI", fontName=BI, fontSize=8.5, leading=12, spaceAfter=3, textColor=DGRAY)
bul = ps("Bul",  fontName=BF, fontSize=9.5, leading=13.5, spaceAfter=3, leftIndent=14)
cav = ps("Cav",  fontName=BI, fontSize=8.5, leading=12,   spaceAfter=3, leftIndent=12, textColor=DGRAY)
ftr = ps("Ftr",  fontName=BF, fontSize=7.5, leading=10,   textColor=colors.gray, alignment=TA_CENTER)
sec_lbl = ps("SecLbl", fontName=BB, fontSize=13, leading=17, textColor=NAVY, alignment=TA_CENTER, spaceAfter=4, spaceBefore=4)
meta    = ps("Meta",   fontName=BI, fontSize=8,  leading=11, textColor=colors.gray, spaceAfter=8)
tbl_hdr = ps("TblHdr",   fontName=BB, fontSize=8, leading=11, textColor=colors.white)
tbl_bod = ps("TblBod",   fontName=BF, fontSize=8, leading=11, textColor=colors.black)
tbl_bold = ps("TblBold", fontName=BB, fontSize=8, leading=11, textColor=NAVY)
oneliner= ps("OneLiner", fontName=BB, fontSize=10, leading=14, spaceAfter=6, backColor=colors.HexColor("#FFF8F8"))
flag_st = ps("Flag", fontName=BF, fontSize=8.5, leading=12, spaceAfter=4, leftIndent=14)
verdict = ps("Verdict", fontName=BF, fontSize=9.5, leading=13.5, spaceAfter=4, backColor=CREAM, leftIndent=6, rightIndent=6)
content_item = ps("ContentItem", fontName=BF, fontSize=10, leading=15, spaceAfter=2, leftIndent=18)

# ── Helpers ────────────────────────────────────────────────────────────────────
def hr(color=MGRAY, thick=0.75, before=3, after=3):
    return HRFlowable(width="100%", thickness=thick, color=color, spaceAfter=after, spaceBefore=before)

def thick_hr():
    return hr(NAVY, 1.5, 4, 4)

def section_divider(title):
    return [
        PageBreak(),
        Spacer(1, 0.3*inch),
        thick_hr(),
        Paragraph(title, sec_lbl),
        thick_hr(),
        Spacer(1, 0.15*inch),
    ]

def sep():
    return [Spacer(1, 4), hr(), Spacer(1, 4)]

def txt(s, style=bod):
    """Render paragraph. Caller is responsible for & escaping."""
    return Paragraph(s, style)

def colored_block(content_para, bg):
    """Wrap a paragraph in a 1-cell table to get a reliable background."""
    t = Table([[content_para]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,0), bg),
        ("TOPPADDING",  (0,0), (0,0), 6),
        ("BOTTOMPADDING",(0,0),(0,0), 6),
        ("LEFTPADDING", (0,0), (0,0), 8),
        ("RIGHTPADDING",(0,0),(0,0), 8),
    ]))
    return t

def make_table(data, col_widths, extra_styles=None):
    """Convert all string cells to Paragraphs so text wraps inside cells."""
    wrapped = []
    for i, row in enumerate(data):
        new_row = []
        for j, cell in enumerate(row):
            if isinstance(cell, str):
                if i == 0:
                    sty = tbl_hdr           # white bold — header row
                elif j == 0:
                    sty = tbl_bold          # navy bold — first column
                else:
                    sty = tbl_bod           # plain body
                new_row.append(Paragraph(cell, sty))
            else:
                new_row.append(cell)
        wrapped.append(new_row)

    t = Table(wrapped, colWidths=[c * inch for c in col_widths])
    cmds = [
        ("BACKGROUND",    (0,0),  (-1,0),  NAVY),
        ("ROWBACKGROUNDS",(0,1),  (-1,-1), [colors.white, LGRAY]),
        ("GRID",          (0,0),  (-1,-1), 0.5, MGRAY),
        ("VALIGN",        (0,0),  (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 6),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 6),
    ]
    if extra_styles:
        cmds.extend(extra_styles)
    t.setStyle(TableStyle(cmds))
    return t

def add_hf(canvas, doc):
    canvas.saveState()
    pw, ph = letter
    canvas.setFont(BF, 7.5)
    canvas.setFillColor(colors.gray)
    canvas.drawRightString(pw - 1.25*inch, ph - 0.6*inch,
                           f"Research Debate — SpaceX IPO Proxy Plays   |   {DATE}")
    canvas.drawCentredString(pw/2, 0.5*inch,
                             f"{BRAND}   —   not for distribution   —   {DATE}   —   Page {doc.page}")
    canvas.restoreState()

# ══════════════════════════════════════════════════════════════════════════════
story = []

# ── COVER ──────────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 1.1*inch),
    Paragraph("RESEARCH DEBATE", cover_label),
    Paragraph("SpaceX IPO<br/>Proxy Plays", cover_title),
    Spacer(1, 0.1*inch),
    Paragraph(DATE, cover_sub),
    Paragraph(BRAND, cover_brand),
    Spacer(1, 0.45*inch),
    thick_hr(),
    Spacer(1, 0.15*inch),
    Paragraph("<b>Contents</b>", ps("ContentsHdr", fontName=BB, fontSize=10, leading=14, spaceAfter=6)),
    Paragraph("State of the Debate", content_item),
    Paragraph("Bull Case — Thematic Rotation Note", content_item),
    Paragraph("Bear Case — Short Thesis", content_item),
    Spacer(1, 0.3*inch),
    hr(),
    Spacer(1, 6),
    txt("Fact-checked against public sources as of 18 May 2026. All user-supplied claims "
        "independently verified before appearing in either document. Claims that could not be "
        "confirmed are marked [UNFOUND] or [DIRECTIONAL ESTIMATE].", cav),
    PageBreak(),
]

# ── STATE OF THE DEBATE ────────────────────────────────────────────────────────
story += [
    Spacer(1, 0.2*inch),
    thick_hr(),
    Paragraph("STATE OF THE DEBATE", sec_lbl),
    thick_hr(),
    Spacer(1, 0.1*inch),
    txt(f"SPACEX IPO PROXY PLAYS   •   {DATE}   •   {BRAND}", meta),
    hr(),
    Paragraph("1. CORE DISAGREEMENT", h2),
    txt("The bull frames June 12 as a <b>hard revaluation event</b> — a forced, audited "
        "mark-to-market that proxies haven’t yet fully absorbed. The bear frames it as a "
        "<b>mechanical rotation trigger</b> — capital that already re-rated proxies 120–540% "
        "will rotate directly into SPCX, leaving proxies as exit liquidity. Both cannot be right. "
        "The resolution depends on a single empirical question neither side has answered: how much "
        "of the expected IPO valuation is <i>already</i> in proxy prices vs. still trapped in stale "
        "private-market marks? If SATS has priced $1.75T SpaceX, the bull’s catalyst is spent. "
        "If it has priced $1.2T, re-rating remains live. No one has done this arithmetic on a "
        "share-count-verified basis."),
    hr(),
    Paragraph("2. THREE OPEN QUESTIONS", h2),
    txt("<b>Q1: What is SATS’s actual per-share SpaceX exposure?</b><br/>"
        "Both sides acknowledge the share count post-xAI merger is unconfirmed. The entire SATS "
        "thesis — bull and bear — is load-bearing on a number neither analyst has verified. "
        "This is not a nuance; it is the trade."),
    txt("<b>Q2: Is June 12 a catalyst or a relief valve?</b><br/>"
        "The bull says IPO day is when re-marking becomes mandatory. The bear says it is the moment "
        "proxy capital has permission to rotate. These are not mutually exclusive — both can be "
        "true on different timescales (IPO day pop, followed by week-two unwind). Neither side models "
        "the intraday vs. post-lockup dynamic separately."),
    txt("<b>Q3: Does SpaceX’s revenue deceleration impair the $1.75T floor — or is valuation "
        "narrative-driven regardless?</b><br/>"
        "The bear’s 89→51→18% deceleration and $5B net loss are the most concrete data "
        "points in either document. The bull never addresses them. If SpaceX is priced on narrative "
        "and Starship optionality rather than current earnings, deceleration may be irrelevant to IPO "
        "pricing — but it matters enormously for where SPCX trades 90 days post-IPO, which is "
        "when SATS’s lock-up and spectrum risks crystallise."),
    hr(),
    Paragraph("3. WHERE BOTH SIDES HAVE BLIND SPOTS", h2),
    txt("<b>Bull’s blind spot:</b> Treats the mark-to-market mechanism as inherently value-creating. "
        "It is not — it can also confirm that proxies are <i>over</i>-priced relative to their SpaceX "
        "exposure. The bull has no answer to the bear’s deceleration data and never models SATS "
        "downside if SpaceX opens below $1.4T."),
    txt("<b>Bear’s blind spot:</b> Assumes rational capital rotation from proxies to SPCX. But SATS "
        "is not a pure SpaceX proxy — it is a DISH/EchoStar restructuring with a SpaceX stake "
        "attached. If index mechanics force SPCX inclusion and SATS is simultaneously re-rated as a "
        "telecom turnaround, the rotation assumption breaks. The bear also conflates RKLB/LUNR "
        "(operational companies with their own revenue) with SATS/DXYZ (financial holding structures) "
        "— the short logic applies cleanly to the latter, not obviously to the former."),
    hr(),
    Paragraph("4. VERDICT", h2),
]
story.append(colored_block(
    txt("<b>The bear has the stronger short-term logic; the bull has the better trade structure.</b> "
        "The re-rate in RKLB/LUNR/DXYZ is almost certainly complete — shorting crowded momentum "
        "into a known catalyst is not a high-conviction setup, but the bear is right that these names "
        "offer asymmetric downside post-June 12. SATS is the genuine dispute: it is either a "
        "sum-of-parts re-rating event or a complexity trap, and the answer requires verified share "
        "counts and a SpaceX opening print. The bull’s discipline — hard kill at $115, trim "
        "50% on IPO day regardless — is the correct posture given this uncertainty. "
        "<b>The trade worth owning is SATS long with the bull’s stop, not RKLB or DXYZ.</b> "
        "GOOGL is the cleanest expression if the goal is SpaceX exposure without structural risk: "
        "the stake is large, under-modeled, and the downside is a diversified mega-cap, not a "
        "telecom restructuring.", verdict),
    CREAM))

# ── BULL CASE ─────────────────────────────────────────────────────────────────
story += section_divider("BULL CASE — THEMATIC ROTATION NOTE")
story += [
    txt(f"THEMATIC STRATEGY   •   {DATE}   •   {BRAND}",
        ps("BullHdr", fontName=BB, fontSize=8.5, leading=12, textColor=colors.HexColor("#444444"), spaceAfter=3)),
    Paragraph("SpaceX IPO Proxies: Marking to Market Before the Bell Rings", h1),
    txt("Structured for position initiation, not commentary. IPO target: June 12, 2026 (Nasdaq: SPCX).", cav),
]
story += sep()

# 01 Cycle Frame
story += [
    Paragraph("01 — CYCLE FRAME", h2),
    txt("The SpaceX pre-IPO proxy trade is entering its late-consensus phase. Every retail aggregator "
        "and most sell-side desks now have a version of the “buy SATS/DXYZ before the SpaceX IPO” "
        "note. The trade has been live long enough that some proxies have repriced dramatically — "
        "<b>SATS up 543% in twelve months</b>, <b>DXYZ trading at ~94% premium to its Q1 2026 "
        "NAV of $24.56/share</b> — meaning the easy money in the most crowded expressions is already made."),
    txt("The remaining opportunity is structural: <b>the act of SpaceX going public forces a formal, "
        "audited mark-to-market on every position that holds SpaceX equity.</b> That re-marking is not "
        "optional, not gradual, and not subject to private-market discount. It happens on IPO day."),
    txt("Two rotation paths are simultaneously live: (a) <b>MARK-TO-MARKET RE-RATING</b> — "
        "holders of SpaceX equity must revalue positions to public market prices on IPO day; "
        "(b) <b>INDEX MECHANICS AMPLIFICATION</b> — Nasdaq reduced its inclusion waiting period "
        "to 15 trading days, the S&amp;P 500 is reviewing fast-track rules (feedback due May 28), "
        "and passive demand at SPCX inclusion is estimated at $30B–$55B. "
        "[The Street, Seeking Alpha, 247 Wall St., May 2026]"),
]
story += sep()

# 02 Candidate Themes
story.append(Paragraph("02 — CANDIDATE THEMES", h2))
proxies = [
    ("A. SATS — EchoStar Corp.", "PURE-PLAY PROXY",
     "Holds ~2.0–2.2% of SpaceX (post-xAI merger). At $1.75T IPO, stake marks at ~$38.5B — essentially "
     "SATS’s entire market cap. Sum-of-parts stub (spectrum assets, orbital rights) currently priced at near-zero "
     "or negative. IPO forces formal sell-side model updates. New Street Research publicly flagged SATS as hidden "
     "SpaceX proxy with ‘meaningful upside.’ [Seeking Alpha, May 2026]",
     "S-1 release May 15–22 • IPO pricing June 11 • Nasdaq listing June 12 • S&amp;P fast-track May 28",
     "Fails if: SpaceX prices below $1.25T; IPO delayed past Aug 2026; adverse tax event on spectrum-for-stock exchange"),
    ("B. GOOGL — Alphabet Inc.", "MEGA-CAP EMBEDDED",
     "Google holds ~5–6.11% of SpaceX (Alaska regulatory filing; diluted post-xAI merger). At $1.75T, stake worth "
     "~$87.5B. Carried at $900M 2015 cost basis — sell-side models have zero for SpaceX. IPO converts illiquid "
     "undisclosed asset to marked liquid holding. Bloomberg: $100B windfall. Google in discussions over orbital "
     "data centers. [TradingKey, May 2026]",
     "S-1 public release • IPO day June 12 • Google/SpaceX orbital data center announcement • Q2 earnings (late July)",
     "Fails if: SpaceX prices below $1.5T; management signals unfavorable stake disposition; sell-the-news rotation"),
    ("C. DXYZ — Destiny Tech100", "PREMIUM-TO-NAV / SQUEEZE PLAY",
     "Closed-end fund (NYSE). NAV $24.56/share Q1 2026; trades at ~$47.62 (94% premium). SpaceX = 16.2% of portfolio. "
     "Bull case is short-squeeze mechanics on IPO day, not clean NAV recovery. Short interest est. 10–20% of float. "
     "$1B ATM offering ongoing — caps sustainable premium. [Quiver Quantitative; SEC filings, 2026]",
     "SpaceX IPO day June 12: 16.2% position marks up; short squeeze potential",
     "Fails if: IPO prices below level implied by 94% NAV premium (~$2.2T effective); ATM dilution overwhelms squeeze"),
    ("D. NASA — Tema Space Innovators ETF", "THEMATIC BASKET",
     "Launched March 30 2026. SpaceX top holding at ~10% via SPV, marked at ~$1.56T (conservative vs. $1.75T target). "
     "Expense ratio 0.75%. Least crowded of direct-exposure vehicles. Post-IPO: sector re-rating lifts space-economy basket. "
     "[Tema ETFs, March 2026; Seeking Alpha, May 2026]",
     "SpaceX IPO June 12 • Post-IPO sector re-rating across space-economy basket",
     "SPV fee structure unverified — value-flow mechanics unclear. Verify before sizing."),
    ("E. XOVR — ERShares Crossover ETF", "AVOID PRE-IPO",
     "SpaceX ~18% of AUM via SPV. ETF.com documented ‘XOVR SpaceX Meltdown’: SpaceX marked $135→$526 "
     "in Feb 2026 but NAV barely moved. $626M single-day outflows. SEC 15% illiquid-holdings cap breached. "
     "Post-IPO only if SPV dissolves cleanly. [ETF.com, 2026]",
     "Post-IPO only: SPV potentially converts to direct ownership",
     "SPV fees or provisions permanently impair value flow. Avoid pre-IPO."),
]
for name, tag, thesis, cats, bear in proxies:
    story += [
        Paragraph(name, h3),
        txt(f"<i>{tag}</i>",
            ps(f"tag_{name[:4]}", fontName=BI, fontSize=8, leading=11, textColor=DGRAY, spaceAfter=3)),
        txt(f"<b>THESIS</b> {thesis}"),
        txt(f"<b>CATALYSTS</b> {cats}"),
        txt(f"<i>Bear case: {bear}</i>", cav),
        hr(MGRAY, 0.5),
    ]

story += sep()

# 03 Ranking
story.append(Paragraph("03 — RANKING", h2))
story.append(make_table(
    [["#", "VEHICLE", "KEY JUSTIFICATION", "FAILURE CONDITION"],
     ["1", "SATS",     "SpaceX stake ~= market cap. Any IPO $1.5T+ forces formal SOTP validation.",
                        "IPO delays to 2027; prices below $1.25T; adverse tax event"],
     ["2", "GOOGL",    "$87–$100B stake not in any sell-side model. Zero structural complexity.",
                        "IPO below $1.5T; mgmt unfavorable disposition; sell-the-news"],
     ["3", "DXYZ",     "Highest beta to IPO day; short squeeze mechanics. Trade is the squeeze, not NAV.",
                        "IPO below implied ~$2.2T; ATM dilution overwhelms squeeze"],
     ["4", "NASA ETF", "Least crowded direct-exposure vehicle; sector re-rating overlay post-IPO.",
                        "SPV structure impairs value flow (unverified)"],
     ["5", "XOVR",     "Avoid pre-IPO. Post-IPO only if SPV dissolves cleanly.",
                        "SPV impairment permanent; SEC compliance sale forced"]],
    [0.3, 0.7, 2.9, 2.1]
))
story += sep()

# 04 Contrarian
story += [
    Paragraph("04 — CONTRARIAN / NON-CONSENSUS PICK: GOOGL", h2),
    txt("Absent from standard SpaceX-proxy rotation lists because it requires owning a $4.8T mega-cap for a ~2% NAV "
        "uplift. Retail gravitates to DXYZ/SATS for higher leverage. Institutional desks ignored GOOGL because the "
        "stake was undisclosed until the Alaska regulatory filing surfaced in early 2026."),
    txt("Three asymmetries: (1) Stake value ($87–$100B) exceeds the entire market cap of most dedicated proxy "
        "vehicles. (2) Sits in a liquid index-weight mega-cap with no SPV risk, no NAV premium risk, no illiquidity "
        "risk. (3) IPO triggers a sell-side model-update cycle — every DCF/SOTP for GOOGL had zero for SpaceX."),
    txt("Additional catalyst: Google is negotiating orbital data centers with SpaceX [TradingKey, May 2026] — "
        "converts a passive investment gain into a strategic partnership re-rating."),
    txt("<i>Bear case: GOOGL too large for 2% uplift to move the stock. IPO premium partially pre-traded "
        "(GOOGL +29.9% in 30 days). Management may donate or distribute the stake. Size conservatively.</i>", cav),
]
story += sep()

# 05 Tradeable Expression
story.append(Paragraph("05 — TRADEABLE EXPRESSION", h2))
story.append(make_table(
    [["DIMENSION",    "SATS (Core)",                                      "GOOGL (Contrarian)"],
     ["Entry",        "~$138. Scale pre-roadshow (before June 4)",   "~$395 current. Models not yet updated"],
     ["Exit ↑",  "$155–165 post-IPO SOTP update",               "+5–7% attributable to SpaceX catalyst"],
     ["Exit ↓",  "$115 kill — delay past Aug 2026 OR SpaceX prices <$1.25T", "No explicit stop — quality mega-cap"],
     ["Hedge",        "Long SATS / short XLC (1:0.5 beta-adj)",           "Long GOOGL / short IWM to strip beta"],
     ["Horizon",      "4–6 weeks. Trim 50% on IPO day regardless",   "6–12 months. Model-update cycle"],
     ["Size pre",     "3–4% book",                                   "2–3% book as overweight vs. benchmark"],
     ["Size post",    "5–6% after S-1 confirms SpaceX financials",   "4% if orbital data center announced"]],
    [1.25, 2.375, 2.375]
))
story += sep()

# 06 Monitor
story.append(Paragraph("06 — WHAT TO MONITOR", h2))
story.append(make_table(
    [["SIGNAL", "DETAILS"],
     ["SpaceX S-1 Release",      "May 15–22 window. Formalises $18.5B 2025 revenue, margins, share count. "
                                  "Deviation from $1.75T target forces model revisions. [Motley Fool, Apr 27 2026]"],
     ["S&P 500 Fast-Track",      "Feedback due May 28. If approved: est. $30–$55B passive demand at SPCX inclusion. "
                                  "Denial removes amplification but not the mark-to-market thesis. [247 Wall St., May 2026]"],
     ["Roadshow Start",          "June 4 expected. Reports of oversubscription above $1.75T = positive. "
                                  "Tepid demand or pricing revision downward = kill condition."],
     ["SATS Share Count",        "SATS Q1 2026 10-Q on SEC EDGAR. Verify: exact SpaceX share count post-xAI merger, "
                                  "tax treatment of spectrum-for-stock exchange, net debt."],
     ["GOOGL Model Updates",     "First sell-side note post-S-1 incorporating SpaceX SOTP into GOOGL price target "
                                  "triggers model-update cycle. Target: Goldman, Morgan Stanley, UBS."],
     ["IPO Delay Signals",       "Any report of postponement past Aug 2026 = full SATS exit trigger. "
                                  "Monitor CNBC David Faber, Bloomberg. AFL-CIO/AFT union warnings submitted to SEC."]],
    [1.5, 4.5]
))
story += sep()

# VAL
story += [
    Paragraph("VAL — RETURN FRAMEWORK   (SATS lead vehicle)", h2),
    txt("[Method 1 — SpaceX IPO mark-to-market]: SATS SpaceX stake at $1.75T = ~$38.5B gross. "
        "SATS market cap ~$38–$40B. Implies stub priced at zero or negative. Post-IPO stub re-rating: ~$3–$5B. "
        "Implied SATS fair value: $142–$156/share vs. ~$138 current.   <b>60% weight</b>"),
    txt("[Method 2 — S&amp;P 500 fast-track passive demand]: $30–$55B passive buying supports SpaceX "
        "at or above IPO level. Removes risk of post-IPO SpaceX price collapse compressing SATS mark.   "
        "<b>40% weight (risk-reduction)</b>"),
    txt("<b>BLENDED TARGET RETURN: +8–15% SATS vs. current   •   HORIZON 4–6 weeks   •   "
        "+5–10% excess vs. S&amp;P</b>"),
    txt("GOOGL overlay: $87–$100B mark-to-market = 1.8–2.1% pure uplift + 1–2% sell-side model-update "
        "cycle + orbital data center upside (unscheduled): +3–5%.   "
        "<b>GOOGL TARGET: +3–7% | HORIZON 6–12 months</b>"),
]
story.append(hr())

# SCENARIOS
story.append(Paragraph("SCENARIOS — 25% BEAR / 50% BASE / 25% BULL", h2))
scen_bgs = [BEAR_C, BASE_C, BULL_C, BLEND_C]
scen_raw = [
    ["",        "Conditions",
     "SATS\n3M / 6M / 12M",     "GOOGL\n3M / 6M / 12M"],
    ["BEAR\n25%",
     "SpaceX IPO <$1.25T; passive inclusion denied; SATS mark below market cap",
     "-25% / -30% / -20%",      "-3% / -5% / -5%"],
    ["BASE\n50%",
     "SpaceX IPO at $1.75T; S&amp;P fast-track approved; passive demand $30–$55B",
     "+10% / +15% / +20%",      "+3% / +5% / +8%"],
    ["BULL\n25%",
     "SpaceX prices at $2T+; same-day S&amp;P inclusion; orbital data center announced",
     "+25% / +35% / +40%",      "+7% / +10% / +15%"],
    ["BLENDED",  "",
     "+6% / +9% / +14%",        "+3% / +4% / +7%"],
]
scen_cols = [0.6*inch, 2.5*inch, 1.45*inch, 1.45*inch]
# Wrap every cell in a Paragraph so text reflows
scen_wrapped = []
for i, row in enumerate(scen_raw):
    new_row = []
    for j, cell in enumerate(row):
        if i == 0:
            sty = tbl_hdr
        elif j == 0:
            sty = ps(f"ScenLbl{i}", fontName=BB, fontSize=8, leading=11,
                     textColor=NAVY)
        else:
            sty = tbl_bod
        new_row.append(Paragraph(cell, sty))
    scen_wrapped.append(new_row)

scen_table = Table(scen_wrapped, colWidths=scen_cols)
scen_table.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0), NAVY),
    ("BACKGROUND",    (0,1), (-1,1), BEAR_C),
    ("BACKGROUND",    (0,2), (-1,2), BASE_C),
    ("BACKGROUND",    (0,3), (-1,3), BULL_C),
    ("BACKGROUND",    (0,4), (-1,4), BLEND_C),
    ("GRID",          (0,0), (-1,-1), 0.5, MGRAY),
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ("TOPPADDING",    (0,0), (-1,-1), 5),
    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ("LEFTPADDING",   (0,0), (-1,-1), 6),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
]))
story.append(scen_table)
story.append(Spacer(1, 6))
story.append(hr())

# SENSITIVITY
story.append(Paragraph("SENSITIVITY", h2))
story.append(make_table(
    [["Variable", "Shock", "SATS Impact", "GOOGL Impact"],
     ["SpaceX IPO valuation",       "$1.75T → $1.25T (-$500B)",   "-20–25%",        "-2%"],
     ["S&P fast-track denied",      "Passive demand absent",            "-5–8%",           "Negligible"],
     ["IPO delay 1 quarter",        "Sept 2026 push",              "-15% / full exit",     "Minimal"],
     ["GOOGL tax on $99B gain",     "21% federal rate",                 "n/a",                  "-33% of net uplift"],
     ["Orbital data center deal",   "Strategic re-rating",              "n/a",                  "+3–5%"],
     ["SpaceX prices at $2T",       "Bull case",                        "+15–20%",         "+3%"]],
    [1.9, 1.9, 1.1, 1.1]
))
story.append(Spacer(1, 6))
story.append(hr())

# TRADES
story.append(Paragraph("TRADES", h2))
for arrow, label, detail in [
    ("→ CORE",   "SATS",
     "entry ~$138   •   exit ↑ $155–165 (post-IPO SOTP)   •   "
     "exit ↓ $115 (kill: delay past Aug 2026 OR SpaceX <$1.25T)"),
    ("→ OVERLAY","GOOGL",
     "add to existing ~$395   •   target +5–7% over 6–12 months   •   no explicit stop"),
    ("→ EVENT",  "SATS into June 12",
     "trim 50% at open on IPO day regardless of direction — event risk symmetry"),
    ("→ HEDGE",  "Long SATS / short XLC",
     "1:0.5 beta-adjusted ratio   •   cover short if IPO confirmed oversubscribed at $1.75T+"),
    ("✕ AVOID",  "XOVR pre-IPO",
     "SPV structural impairment confirmed   •   DXYZ: tactical only, stop below $43"),
]:
    story.append(txt(
        f"<b>{arrow} {label}</b> {detail}",
        ps(f"tr_{label[:4]}", fontName=BF, fontSize=9, leading=13, spaceAfter=3, leftIndent=6)
    ))

story.append(hr())

# SIZING
story.append(Paragraph("SIZING", h2))
story.append(colored_block(
    txt("<b>SATS: $400K–$600K notional   •   3–4% book   •   "
        "pre-catalyst — scale to 5–6% on S-1 release   "
        "← ENTER HERE</b><br/>"
        "GOOGL: 2–3% book overweight; extend to 4% on orbital data center announcement<br/>"
        "DXYZ: 1% book maximum — tactical only — stop $43<br/>"
        "<b>MAX 8% NAV combined SpaceX proxy exposure   •   "
        "EXP RETURN (prob-weighted) SATS +6% / GOOGL +3%   •   "
        "MAX DRAWDOWN TOLERANCE 15% on SATS before reassessment</b>"),
    LGRAY))
story.append(Spacer(1, 8))
story.append(hr())

# TIME-SENSITIVE FLAGS (Bull)
story.append(Paragraph("TIME-SENSITIVE FLAGS &amp; LOW-CONFIDENCE CAVEATS", h2))
bull_flags = [
    ("SPACEX IPO VALUATION RANGE",
     "User stated $1.75T — confirmed multi-source (CNBC, Bloomberg, Reuters, April 2026). "
     "Bloomberg cites targets ‘above $2T.’ This note uses $1.75T base / $2T bull. No conflict."),
    ("SATS SHARE COUNT AND NET DEBT",
     "Sum-of-parts uses ~288M diluted shares and ~$38–$40B market cap from May 2026 sources. "
     "Exact Q1 2026 net debt and SpaceX share count not verified from primary SEC filing. "
     "Single source for 52M SpaceX share count (techi.com, 2026) — treat as directional estimate. "
     "Verify against SATS 10-Q on SEC EDGAR before executing."),
    ("GOOGL STAKE SIZE POST-xAI MERGER",
     "Original stake 6.11% (Alaska filing, multi-source). Post-xAI merger dilution to ~5% per Bloomberg "
     "(April 2026). Exact post-merger share count not disclosed. $87–$100B reflects 5–5.7% at "
     "$1.75T–$2T — directional estimate until S-1 discloses full cap table."),
    ("GOOGL TAX LIABILITY",
     "Not modeled in public sell-side reports as of May 2026. Cost basis: $900M (2015). At $1.75T SpaceX "
     "IPO, unrealized gain ~$86–$99B. Corporate tax at 21% = ~$18–$21B on realization. "
     "Alphabet will NOT be forced to sell on IPO day (lock-up applies)."),
    ("SATS LOCK-UP / TAX TREATMENT",
     "Tax treatment of spectrum-for-stock exchange (taxable vs. tax-deferred) not confirmed. "
     "If taxable, SATS faces cash drain reducing stub value. Single source. Verify with SATS 10-K."),
    ("DXYZ ATM OFFERING",
     "Destiny Tech100 filed $1B ATM offering — confirmed (SEC filing, Stocktitan.net, 2026). "
     "Ongoing dilution caps sustainable premium and may suppress short-squeeze catalyst."),
    ("XOVR SPV IMPAIRMENT",
     "Confirmed by ETF.com (2026): SpaceX gains did not flow fully to XOVR NAV in Feb 2026. "
     "Specific SPV contractual terms not publicly disclosed. Do not size pre-IPO."),
    ("S&P 500 FAST-TRACK RULE",
     "Pending S&amp;P committee review; feedback due May 28 2026; not yet implemented. "
     "Treated as base-case scenario, not confirmed event."),
]
for title, text in bull_flags:
    story.append(txt(f"<b>{title}:</b> {text}", flag_st))

# ── BEAR CASE ─────────────────────────────────────────────────────────────────
story += section_divider("BEAR CASE — SHORT THESIS")
story += [
    txt(f"SHORT THESIS — SPACEX IPO PROXY PLAYS   •   {DATE}   •   {BRAND}",
        ps("BearHdr", fontName=BB, fontSize=8.5, leading=12, textColor=colors.HexColor("#444444"), spaceAfter=3)),
]
story += sep()

story.append(Paragraph("1. THE CASE IN ONE LINE", h2))
story.append(colored_block(
    txt("Retail is buying SATS, RKLB, LUNR, and DXYZ as free-options on a SpaceX mark-to-market re-rate; "
        "the re-rate already happened, the fundamentals never arrived, and June 12 is a sell-the-news "
        "event, not a catalyst.", oneliner),
    colors.HexColor("#FFF8F8")))
story += sep()

story.append(Paragraph("2. WHAT THE BULLS ARE MISSING", h2))
for title, body_text in [
    ("Assumption A: Proxies haven’t priced in the IPO yet",
     "Wrong. RKLB is up 131% since March 30, 2026 alone. LUNR is up 123% over the same window. "
     "SATS has rallied 543% over the trailing 12 months. DXYZ was trading at a ~45–50% premium to "
     "its December 2025 NAV of $19.97/share as recently as April 2026. The re-rate has already occurred."),
    ("Assumption B: SATS’s SpaceX stake converts cleanly to NAV at IPO",
     "Disputed. Requires simultaneously: (a) SpaceX lists at or above $1.75T, (b) no material lock-up "
     "haircut — waivers being ‘considered’ but not confirmed; standard 90–180-day hold potentially "
     "applies, (c) FCC closes spectrum transfers on the November 2027 target on schedule, "
     "(d) legacy DISH/Sling/Boost/Hughes businesses don’t impair equity bridge. All four must hold simultaneously."),
    ("Assumption C: $1.75T is a floor, not a ceiling",
     "Wrong. SpaceX revenue growth decelerated 89% (2023) → 51% (2024) → 18% (2025). Net loss $5B "
     "in 2025 driven by xAI integration. xAI revenues ~$500M at $250B ascribed value = 500x trailing revenue. "
     "At $1.75T, the combined entity trades at ~87–94x 2025 trailing revenue. NYU’s Aswath Damodaran: "
     "investors ‘have already decided SpaceX is a great buy and are now working backwards to justify the price.’"),
]:
    story += [
        Paragraph(title, h3),
        txt(body_text),
    ]
story += sep()

story.append(Paragraph("3. THE DATA THEY’RE NOT SHOWING YOU", h2))
for dp in [
    "SpaceX revenue growth decelerated sharply: 89% → 51% → 18% over 2023–2025. $5B net loss in 2025. "
    "Bulls are extrapolating peak-cycle growth rates into a decelerating business.",
    "xAI poisons the multiple: EU regulatory probes against Grok flagged as material risk in SpaceX’s own S-1. "
    "Any adverse ruling compresses the $250B xAI valuation — the most fragile component of the stack.",
    "Governance is the most management-favorable in modern IPO history: Musk retains 83.8% voting control "
    "via Class B shares (10:1 ratio) on 42.5% economic interest. Texas laws make shareholder action nearly "
    "impossible. CalPERS and New York pension officials have written to Musk objecting. "
    "Index-forced buyers become exit liquidity for insiders.",
    "RKLB is not cheap because SpaceX is expensive: P/S ~74x trailing sales at ~$80B market cap. "
    "SpaceX CFO Adam Spice warned the IPO ‘could put weak space stocks into obscurity.’ "
    "RKLB short interest 5.5% of float; $1.9B in YTD mark-to-market losses on bears — squeezed but fundamentals unchanged.",
    "The IPO itself is a liquidity vacuum: BlackRock eyeing up to $10B in the deal. At $75–$80B projected "
    "raise — largest capital absorption event in equity market history — rotation out of proxies and "
    "into direct SPCX is structurally inevitable on or after June 12.",
]:
    story.append(txt(f"• {dp}", bul))
story += sep()

story.append(Paragraph("4. SHORT CATALYSTS", h2))
for cat_title, cat_body in [
    ("Catalyst 1 — June 12, 2026: SPCX lists and proxy capital rotates",
     "SPCX begins trading. Direct ownership becomes available to every investor currently holding proxies. "
     "Rational trade: sell proxy, buy underlying. Polymarket: 67% implied probability of June listing — "
     "the event is expected. Expected events that trigger mechanical selling are the definition of sell-the-news."),
    ("Catalyst 2 — EU regulatory action against xAI/Grok, Q3 2026",
     "SpaceX S-1 flags ongoing EU regulatory probes against Grok as a material risk. Any adverse ruling "
     "directly attacks the $250B xAI valuation. A 20% markdown on xAI alone reduces blended SpaceX "
     "valuation by ~$50B, compressing SATS NAV and DXYZ net asset value proportionately."),
    ("Catalyst 3 — Lock-up expiry / insider selling window, Sept–Dec 2026",
     "Standard 90-day lock-up from June 12 expires mid-September. SpaceX is ‘considering’ waiving "
     "lock-ups — meaning insider selling could begin Day 1. SpaceX conducted tender offers at $185 "
     "(Dec 2024), $212 (Jul 2025), and $421 (Dec 2025); employees sitting on 4–9x cost basis. "
     "Supply overhang from employee monetization is structurally bearish for sustained post-IPO multiples."),
]:
    story += [Paragraph(cat_title, h3), txt(cat_body)]
story += sep()

story.append(Paragraph("5. WHAT WOULD MAKE ME COVER", h2))
for c in [
    "Cover if SpaceX reports Q1/H1 2026 revenue re-acceleration above 35% growth, demonstrating xAI "
    "integration is expanding revenue. Current trajectory is 18% with $5B net loss.",
    "Cover if lock-up terms are confirmed as 180 days with no waiver AND FCC formally approves SATS spectrum "
    "transfers ahead of schedule. Removes both the supply overhang and the critical SATS NAV uncertainty simultaneously.",
    "Cover if SPCX opens below $1.4T implied market cap on IPO day — the bear case has already played out.",
]:
    story.append(txt(f"• {c}", bul))
story += sep()

story.append(Paragraph("6. PRICE TARGET / DOWNSIDE SCENARIO", h2))
story.append(make_table(
    [["Name",  "Current",                   "Bear Target",          "Down-\nside", "Key Assumption"],
     ["SATS",  "~$138/share",               "$80–$95",              "45–55%",
      "SpaceX lists at $1.4T; 30% lock-up haircut; FCC 6-month delay; legacy impairment"],
     ["RKLB",  "~$26\n(~$80B mkt cap)",     "$13–$15",              "40–50%",
      "Post-IPO re-rates to 35–40x sales as direct SpaceX comparison depresses premium"],
     ["DXYZ",  "~$47.62\n(94% NAV prem.)",  "Reverts to NAV\n~$24–$25", "30–33%",
      "SpaceX listing removes case for closed-end fund premium over direct SPCX ownership"]],
    [0.65, 1.2, 1.2, 0.65, 2.3],
    extra_styles=[
        ("BACKGROUND", (0,1), (-1,1), BEAR_C),
        ("BACKGROUND", (0,2), (-1,2), colors.HexColor("#FFF8F8")),
        ("BACKGROUND", (0,3), (-1,3), BEAR_C),
    ]
))
story += [
    Spacer(1, 6),
    txt("DIRECTIONAL ESTIMATE: All price targets derived from scenario analysis and comparable valuation; "
        "not from audited financials. Treat as directional until SpaceX S-1 confirms cap table and revenue figures.", cav),
    hr(),
    Paragraph("LOW-CONFIDENCE FLAGS", h2),
]
for lc in [
    "xAI revenue figure of ~$500M (2025) sourced from secondary analyst estimates, not audited financials. "
    "S-1 may disclose a materially different number when published ~May 20, 2026.",
    "SATS’s exact SpaceX share count post-xAI merger not confirmed in a post-merger filing reviewed directly. "
    "Dilution impact derived from analyst estimates.",
    "Lock-up waiver reporting characterises SpaceX as ‘considering’ a waiver — unconfirmed and "
    "structurally consequential if the waiver does not materialise.",
    "RKLB short interest figure of 5.5% of float sourced from May 2026 reporting; may have changed. "
    "A short squeeze in RKLB ahead of June 12 is a real risk to this leg of the trade.",
]:
    story.append(txt(f"• {lc}", flag_st))

story += [
    Spacer(1, 20),
    hr(MGRAY, 0.5),
    txt(f"{BRAND} — not for distribution. Forward-looking estimates subject to material revision. {DATE}.", ftr),
]

# ── BUILD ──────────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    leftMargin=1.25*inch, rightMargin=1.25*inch,
    topMargin=1.0*inch,   bottomMargin=1.0*inch,
    title="Research Debate — SpaceX IPO Proxy Plays",
    author="Buy-Side Research",
)
doc.build(story, onFirstPage=add_hf, onLaterPages=add_hf)
print(f"Saved: {OUTPUT}")
