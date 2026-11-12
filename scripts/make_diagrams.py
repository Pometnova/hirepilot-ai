"""Draws docs/images/data_model.svg and docs/images/architecture.svg. The data model is read from the built SQLite database
(data/hirepilot.db), so build it first: .venv/bin/python scripts/build_db.py

Usage:  .venv/bin/python scripts/make_diagrams.py           # writes the two SVG files (no extra packages)
        .venv/bin/python scripts/make_diagrams.py --png     # also writes the PNG files (needs: pip install playwright)
"""
import sqlite3, html
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, Menlo, Consolas, monospace"
BG, TEXT, MUTED, LINE = "#FAF9F8", "#201936", "#777384", "#D9D2E6"
GREEN, BLUE, BROWN, GREY, CORAL, PURPLE = "#2F9E6E", "#3A6FD0", "#8B5E3C", "#7A7790", "#E8553D", "#6B54A3"
esc = html.escape


def head(w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" font-family="{FONT}">'
            f'<rect width="{w}" height="{h}" fill="{BG}"/>')


def text(x, y, s, size=13, weight=400, fill=TEXT, anchor="start", family=None, extra=""):
    fam = f' font-family="{family}"' if family else ""
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{fam}{extra}>{esc(s)}</text>'


def title_block(w, title, caption_lines):
    out = [text(40, 52, title, 30, 700)]
    for i, line in enumerate(caption_lines):
        out.append(text(40, 82 + i * 21, line, 14.5, 400, MUTED))
    return out


def chip(x, y, color, label, size=13):
    return (f'<rect x="{x}" y="{y - 12}" width="16" height="16" rx="4" fill="{color}"/>' + text(x + 24, y + 1, label, size, 500))


def card_path(x, y, w, hh):
    r = 11
    return f"M{x},{y + hh} L{x},{y + r} Q{x},{y} {x + r},{y} L{x + w - r},{y} Q{x + w},{y} {x + w},{y + r} L{x + w},{y + hh} Z"


# ------------------------------------------------------------------ data model
GROUPS = {"People": (GREEN, ["persons", "candidates", "candidate_contacts"]),
          "Hiring pipeline": (BLUE, ["jobs", "job_stages", "applications", "stage_events", "scorecards", "scorecard_scores", "tasks"]),
          "Records linked to a candidate": (BROWN, ["emails", "cvs", "activity_notes"]),
          "Reference and audit": (GREY, ["data_issues", "stage_aliases", "build_meta"])}
POS = {"job_stages": (0, 0), "jobs": (0, 1), "stage_events": (0, 2),
       "tasks": (1, 0), "applications": (1, 1), "scorecards": (1, 2), "scorecard_scores": (1, 3),
       "persons": (2, 0), "candidates": (2, 1), "candidate_contacts": (2, 2),
       "cvs": (3, 0), "emails": (3, 1), "activity_notes": (3, 2),
       "data_issues": (4, 0), "stage_aliases": (4, 1), "build_meta": (4, 2)}
HIDE = {"source_file", "source_id"}
MAX_ROWS = 8


def read_schema():
    con = sqlite3.connect(ROOT / "data" / "hirepilot.db")
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    schema = {}
    for t in tables:
        cols = con.execute(f"pragma table_info({t})").fetchall()
        fks = {f[3]: (f[2], f[4]) for f in con.execute(f"pragma foreign_key_list({t})")}
        pk = [c[1] for c in cols if c[5]]
        schema[t] = {"cols": [c[1] for c in cols], "pk": pk, "fk": fks}
    return schema


def shown_rows(t, info):
    keys = [c for c in info["cols"] if c in info["pk"] or c in info["fk"]]
    extras = [c for c in info["cols"] if c not in keys and c not in HIDE]
    room = max(MAX_ROWS - len(keys), 0)
    rows = keys + extras[:room]
    rows = [c for c in info["cols"] if c in rows]          # keep the table's own order
    more = len(info["cols"]) - len(rows)
    return rows, more


def data_model():
    schema = read_schema()
    n = len(schema)
    assert set(schema) == {t for _, (_, ts) in GROUPS.items() for t in ts}, "diagram groups do not match the real tables"
    W, GAP, X0, ROWH, HDR = 290, 62, 40, 19, 32
    color = {t: c for _, (c, ts) in GROUPS.items() for t in ts}
    cards = {}
    for t, info in schema.items():
        rows, more = shown_rows(t, info)
        h = HDR + len(rows) * ROWH + (ROWH if more else 0) + 12
        cards[t] = {"rows": rows, "more": more, "h": h}
    nrows = 4
    row_h = [max(cards[t]["h"] for t, (c, r) in POS.items() if r == i) for i in range(nrows)]
    tops = [200]
    for i in range(nrows - 1):
        tops.append(tops[-1] + row_h[i] + 54)
    for t, (c, r) in POS.items():
        cards[t].update(x=X0 + c * (W + GAP), y=tops[r], w=W)
    width = X0 * 2 + 5 * W + 4 * GAP
    height = tops[-1] + row_h[-1] + 40
    # --- relations
    rels = []
    for t, info in schema.items():
        for col, (pt, pcol) in info["fk"].items():
            rels.append({"child": t, "col": col, "parent": pt, "pcol": pcol, "dashed": col == "person_id" and t != "candidates"})
    def ycenter(t, col):
        c = cards[t]
        if col in c["rows"]:
            return c["y"] + HDR + c["rows"].index(col) * ROWH + ROWH / 2 + 2
        return c["y"] + HDR / 2
    gutter_n, gutter_i, vert_i = {}, {}, {}
    for r in rels:
        cc, pc = POS[r["child"]][0], POS[r["parent"]][0]
        r["kind"] = "v" if cc == pc else "h"
        if r["kind"] == "h":
            g = min(cc, pc)
            assert abs(cc - pc) == 1, r
            gutter_n[g] = gutter_n.get(g, 0) + 1
    lines, marks = [], []
    def fork(px, py, dx, dy, col):          # crow's foot at the card edge (px,py); (dx,dy) points away from the card
        bx, by = px + dx * 16, py + dy * 16
        nx, ny = -dy, dx
        s = ""
        for k in (-7, 0, 7):
            s += f'<line x1="{bx}" y1="{by}" x2="{px + nx * k}" y2="{py + ny * k}" stroke="{col}" stroke-width="1.6"/>'
        return s
    def bar(px, py, dx, dy, col):
        bx, by = px + dx * 12, py + dy * 12
        nx, ny = -dy, dx
        return f'<line x1="{bx + nx * 7}" y1="{by + ny * 7}" x2="{bx - nx * 7}" y2="{by - ny * 7}" stroke="{col}" stroke-width="1.8"/>'
    vcount = {}
    for r in rels:
        ch, pa = cards[r["child"]], cards[r["parent"]]
        col = "#8E87A3" if r["dashed"] else "#5A5470"
        dash = ' stroke-dasharray="5 4"' if r["dashed"] else ""
        if r["kind"] == "h":
            cc, pc = POS[r["child"]][0], POS[r["parent"]][0]
            g = min(cc, pc)
            i = gutter_i.get(g, 0); gutter_i[g] = i + 1
            gx = X0 + (g + 1) * W + g * GAP + GAP / 2 + (i - (gutter_n[g] - 1) / 2) * 9
            if pc < cc:      # parent on the left: child's left edge -> parent's right edge
                xs, xe, d = ch["x"], pa["x"] + W, -1
            else:
                xs, xe, d = ch["x"] + W, pa["x"], 1
            ys, ye = ycenter(r["child"], r["col"]), ycenter(r["parent"], r["pcol"])
            lines.append(f'<polyline points="{xs},{ys} {gx},{ys} {gx},{ye} {xe},{ye}" fill="none" stroke="{col}" stroke-width="1.6"{dash}/>')
            marks.append(fork(xs, ys, d, 0, col)); marks.append(bar(xe, ye, -d, 0, col))
        else:
            key = tuple(sorted((r["child"], r["parent"])))
            k = vcount.get(key, 0); vcount[key] = k + 1
            x = ch["x"] + 46 + k * 36
            if ch["y"] > pa["y"]:     # child below parent
                ys, ye, d = ch["y"], pa["y"] + pa["h"], -1
            else:
                ys, ye, d = ch["y"] + ch["h"], pa["y"], 1
            lines.append(f'<line x1="{x}" y1="{ys}" x2="{x}" y2="{ye}" stroke="{col}" stroke-width="1.6"{dash}/>')
            marks.append(fork(x, ys, 0, d, col)); marks.append(bar(x, ye, 0, -d, col))
    out = [head(width, height)]
    out += title_block(width, "HirePilot data model",
                       [f"{n} tables in data/hirepilot.db. Candidates are the hub. Applications carry the hiring process.",
                        "Emails and CVs are linked to candidates by inference, not by an id in the export."])
    # legend
    lx, ly = 40, 140
    for name, (c, _) in GROUPS.items():
        out.append(chip(lx, ly, c, name)); lx += 24 + len(name) * 7.4 + 30
    ly2 = 170
    out.append(f'<rect x="40" y="{ly2 - 12}" width="22" height="16" rx="4" fill="#EFEAF6"/>' + text(51, ly2 + 1, "PK", 9.5, 700, "#4B3F72", "middle"))
    out.append(text(70, ly2 + 1, "primary key", 12.5, 400, MUTED))
    out.append(f'<rect x="170" y="{ly2 - 12}" width="22" height="16" rx="4" fill="#FFE9E4"/>' + text(181, ly2 + 1, "FK", 9.5, 700, "#B23A25", "middle"))
    out.append(text(200, ly2 + 1, "foreign key", 12.5, 400, MUTED))
    out.append(f'<g>{fork(300, ly2 - 4, 1, 0, "#5A5470")}<line x1="300" y1="{ly2 - 4}" x2="330" y2="{ly2 - 4}" stroke="#5A5470" stroke-width="1.6"/></g>')
    out.append(text(340, ly2 + 1, "fork = many", 12.5, 400, MUTED))
    out.append(f'<line x1="440" y1="{ly2 - 4}" x2="470" y2="{ly2 - 4}" stroke="#5A5470" stroke-width="1.6"/>{bar(440, ly2 - 4, 1, 0, "#5A5470")}')
    out.append(text(482, ly2 + 1, "bar = one", 12.5, 400, MUTED))
    out.append(f'<line x1="580" y1="{ly2 - 4}" x2="620" y2="{ly2 - 4}" stroke="#8E87A3" stroke-width="1.6" stroke-dasharray="5 4"/>')
    out.append(text(630, ly2 + 1, "link to the person (one person can have several candidate records)", 12.5, 400, MUTED))
    out += lines + marks
    for t, c in cards.items():
        x, y, h = c["x"], c["y"], c["h"]
        out.append(f'<rect x="{x}" y="{y}" width="{W}" height="{h}" rx="11" fill="#FFFFFF" stroke="{LINE}" stroke-width="1.2"/>')
        out.append(f'<path d="{card_path(x, y, W, HDR)}" fill="{color[t]}"/>')
        out.append(text(x + 14, y + 21, t, 14.5, 700, "#FFFFFF"))
        info = schema[t]
        for i, col in enumerate(c["rows"]):
            ry = y + HDR + i * ROWH + 14
            is_pk, is_fk = col in info["pk"], col in info["fk"]
            if is_pk:
                out.append(f'<rect x="{x + 10}" y="{ry - 11}" width="22" height="15" rx="4" fill="#EFEAF6"/>' + text(x + 21, ry, "PK", 9, 700, "#4B3F72", "middle"))
            if is_fk:
                out.append(f'<rect x="{x + 36}" y="{ry - 11}" width="22" height="15" rx="4" fill="#FFE9E4"/>' + text(x + 47, ry, "FK", 9, 700, "#B23A25", "middle"))
            out.append(text(x + 66, ry, col, 12.5, 600 if is_pk else 400, TEXT, family=MONO))
        if c["more"]:
            ry = y + HDR + len(c["rows"]) * ROWH + 14
            out.append(text(x + 66, ry, f"+ {c['more']} more column{'s' if c['more'] != 1 else ''}", 11.5, 400, MUTED))
    out.append("</svg>")
    (OUT / "data_model.svg").write_text("\n".join(out), encoding="utf-8")
    print("data_model", n, "tables", width, height, "relations", len(rels))
    return n


# ------------------------------------------------------------------ architecture
def arrow(x1, y1, x2, y2, col="#5A5470", dash=False, both=False, label=None, lx=None, ly=None):
    d = ' stroke-dasharray="6 4"' if dash else ""
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="2"{d}/>'
    import math
    def head_(x, y, ang):
        a = 9
        p1 = (x - a * math.cos(ang - 0.45), y - a * math.sin(ang - 0.45)); p2 = (x - a * math.cos(ang + 0.45), y - a * math.sin(ang + 0.45))
        return f'<polygon points="{x},{y} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="{col}"/>'
    ang = math.atan2(y2 - y1, x2 - x1)
    s += head_(x2, y2, ang)
    if both:
        s += head_(x1, y1, ang + math.pi)
    if label:
        s += text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else min(y1, y2) - 8, label, 11, 500, MUTED, "middle")
    return s


def box(x, y, w, h, color, title, sub, lines, mono_lines=False, dashed=False, size=12.5):
    d = ' stroke-dasharray="6 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#FFFFFF" stroke="{color if dashed else LINE}" stroke-width="{1.6 if dashed else 1.2}"{d}/>']
    if not dashed:
        out.append(f'<path d="{card_path(x, y, w, 40)}" fill="{color}"/>')
        out.append(text(x + 14, y + 25, title, 15, 700, "#FFFFFF"))
    else:
        out.append(text(x + 14, y + 25, title, 15, 700, color))
    yy = y + 62
    if sub:
        out.append(text(x + 14, yy, sub, 11.5, 500, MUTED, family=MONO)); yy += 24
    for ln in lines:
        out.append(text(x + 14, yy, ln, size, 400, TEXT, family=MONO if mono_lines else None)); yy += 19
    return out


def architecture():
    W, H = 1900, 840
    BW, GAP, X0, Y0, BH = 205, 60, 40, 290, 330
    xs = [X0 + i * (BW + GAP) for i in range(7)]
    out = [head(W, H)]
    out += title_block(W, "HirePilot architecture",
                       ["A recruiting assistant over the Quillfeather Labs dataset. The data is cleaned once into SQLite. At question time an agent",
                        "calls eight fixed tools, and Python does the calculations while the model explains."])
    lx = 40
    for name, c in (("Data", GREEN), ("Code and logic", BLUE), ("AI", CORAL), ("User interface", PURPLE), ("Checks", GREY)):
        out.append(chip(lx, 140, c, name)); lx += 24 + len(name) * 7.6 + 34
    out.append(f'<line x1="{lx}" y1="136" x2="{lx + 34}" y2="136" stroke="#5A5470" stroke-width="2"/>')
    out.append(text(lx + 44, 141, "data flow", 12.5, 400, MUTED)); lx += 130
    out.append(f'<line x1="{lx}" y1="136" x2="{lx + 34}" y2="136" stroke="#5A5470" stroke-width="2" stroke-dasharray="6 4"/>')
    out.append(text(lx + 44, 141, "optional path or check", 12.5, 400, MUTED))
    # the seven stages
    out += box(xs[0], Y0, BW, BH, GREEN, "Raw files", "data/raw/ (read only)", [
        "candidates.json", "applications.json", "jobs.json", "scorecards.json", "activity.json", "stage_events.csv",
        "emails/*.eml", "cvs/ (CV files)", "", "Never modified.", "Not in this repository."], mono_lines=False, size=12)
    out += box(xs[1], Y0, BW, BH, BLUE, "Loader and cleaning", "backend/ingest/", [
        "Normalises dates and", "stage names.", "Links emails and CVs to", "candidates by inference and", "records method and",
        "confidence of each link.", "", "Every doubtful value gets", "a row in the data-issues", "audit (docs/DATA_AUDIT.md)."], size=12)
    out += box(xs[2], Y0, BW, BH, GREEN, "SQLite", "data/hirepilot.db", [
        "16 tables.", "Built once, then opened", "read-only.", "", "Every row keeps its", "source file and record id.", "",
        "Includes the data_issues", "table (the audit)."], size=12)
    out += box(xs[3], Y0, BW, BH, BLUE, "Services", "backend/services/", [
        "All business logic:", "ranking, funnel, tasks,", "data issues, risk flags.", "", "Python does the", "calculations, filtering", "and dates.",
        "", "Fixed reference date", "2026-10-15."], size=12)
    out += box(xs[4], Y0, BW, BH, BLUE, "MCP server", "backend/mcp_server.py", [
        "8 fixed tools (stdio):", "list_jobs", "get_job", "list_candidates_for_job", "get_candidate_profile", "rank_candidates_for_job", "get_funnel",
        "list_tasks", "get_data_issues", "", "Thin wrapper. No free SQL."], mono_lines=True, size=11.5)
    out += box(xs[5], Y0, BW, BH, CORAL, "Agent core", "backend/agent/", [
        "MCP client + Claude API.", "Starts the server as a", "subprocess, lists the tools,", "runs the tool calls.", "", "The model explains:",
        "FACTS, AI ASSESSMENT,", "CAVEATS, sources.", "", "The model never writes SQL."], size=12)
    uy = Y0
    out += box(xs[6], uy, BW, 155, PURPLE, "Streamlit web app", "web/app.py", ["Overview, Candidates,", "Tasks, Ask AI."], size=12)
    out += box(xs[6], uy + 175, BW, 155, PURPLE, "Slack bot", "slack/bot.py", ["Socket Mode.", "Same agent, answers", "in a thread."], size=12)
    # claude api (above the agent core)
    cx = xs[5]
    out += box(cx, 196, BW, 52, CORAL, "Claude API", None, [], dashed=True)
    # main flow arrows
    mid = Y0 + 150
    labels = ["", "writes", "reads", "calls", "stdio", ""]
    for i in range(5):
        out.append(arrow(xs[i] + BW + 3, mid, xs[i + 1] - 3, mid, label=["cleans", "writes", "reads", "calls", "stdio"][i], ly=mid - 9))
    # agent -> both ui boxes
    ax, ux = xs[5] + BW, xs[6]
    gx = ax + GAP / 2
    out.append(f'<line x1="{ax + 3}" y1="{mid}" x2="{gx}" y2="{mid}" stroke="#5A5470" stroke-width="2"/>')
    out.append(f'<line x1="{gx}" y1="{uy + 78}" x2="{gx}" y2="{uy + 253}" stroke="#5A5470" stroke-width="2"/>')
    out.append(arrow(gx, uy + 78, ux - 3, uy + 78)); out.append(arrow(gx, uy + 253, ux - 3, uy + 253))
    # claude <-> agent
    out.append(arrow(cx + BW / 2, 251, cx + BW / 2, Y0 - 3, both=True))
    out.append(text(cx + BW / 2 + 14, 275, "tool-use loop", 11, 500, MUTED))
    # dashboard path: services -> web app, no AI
    sx, wx = xs[3] + BW / 2, xs[6] + BW / 2
    ry = 172
    out.append(f'<polyline points="{sx},{Y0 - 3} {sx},{ry} {wx},{ry} {wx},{Y0 - 3}" fill="none" stroke="#5A5470" stroke-width="2" stroke-dasharray="6 4"/>')
    import math
    out.append(f'<polygon points="{wx},{Y0 - 1} {wx - 5},{Y0 - 11} {wx + 5},{Y0 - 11}" fill="#5A5470"/>')
    out.append(text((sx + xs[5]) / 2 - 20, ry - 8, "dashboard numbers: the web pages call the services directly, no AI call", 11.5, 500, MUTED, "middle"))
    # side boxes: tests and evals
    ty = Y0 + BH + 56
    out += box(xs[1], ty, 4 * BW + 3 * GAP, 118, GREY, "pytest tests", "tests/", [
        "Run without the API key (a fake agent replaces Claude). Check the loader, the services, the 8 MCP tools,",
        "the web pages and the Slack bot against the raw files."], size=12)
    out += box(xs[5], ty, 2 * BW + GAP, 118, GREY, "Eval set", "evals/", [
        "14 questions with hand-checked facts,", "run against the real agent (paid, on request)."], size=12)
    for i in (1, 3, 4):
        x = xs[i] + BW / 2
        out.append(f'<line x1="{x}" y1="{ty - 1}" x2="{x}" y2="{Y0 + BH + 3}" stroke="#8E87A3" stroke-width="1.8" stroke-dasharray="5 4"/>')
    x = xs[5] + BW / 2
    out.append(f'<line x1="{x}" y1="{ty - 1}" x2="{x}" y2="{Y0 + BH + 3}" stroke="#8E87A3" stroke-width="1.8" stroke-dasharray="5 4"/>')
    out.append("</svg>")
    (OUT / "architecture.svg").write_text("\n".join(out), encoding="utf-8")
    print("architecture", W, H)


def render_png():
    """Optional: SVG -> PNG with a headless browser (Inter from assets/fonts so the text looks the same as in the app)."""
    import re
    from playwright.sync_api import sync_playwright
    font = "".join(f"@font-face{{font-family:'Inter';font-weight:{w};src:url('file://{ROOT}/assets/fonts/Inter-{w}.woff2') format('woff2')}}" for w in (400, 500, 600, 700))
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        for name in ("data_model", "architecture"):
            svg = (OUT / f"{name}.svg").read_text(encoding="utf-8")
            w, h = map(int, re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups())
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1.5)
            page.set_content(f"<html><head><style>{font} body{{margin:0}}</style></head><body>{svg}</body></html>")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f"{name}.png"), clip={"x": 0, "y": 0, "width": w, "height": h})
            print("wrote", OUT / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    import sys
    data_model()
    architecture()
    if "--png" in sys.argv:
        render_png()
