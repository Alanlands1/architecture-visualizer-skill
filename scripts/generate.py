#!/usr/bin/env python3
"""Generate editable PPTX, Draw.io, DOCX, SVG and PNG deliverables from one architecture JSON model.

Every diagram view is laid out once (left to right, following the arrows) and the same
layout is then drawn by each output format, so all files show the same picture.
"""
import argparse, html, json, re, sys, textwrap
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

NAVY = "#183153"; BLUE = "#3069A4"; GREY = "#526579"; TEXT = "#34495E"
CANVAS = "#F7F9FB"; WHITE = "#FFFFFF"; AMBER = "#B56F1C"; RED = "#AA4141"; TEAL = "#198282"
ZONE_LINE = "#8FA3B8"
TYPE_FILL = {"user_interface": "#E8F1FB", "application": "#E8F1FB", "service": "#E6F4F1",
             "database": "#FFF3DF", "external": "#F0ECF8", "queue": "#FCEBEC", "actor": "#F2F4F7",
             "gateway": "#E8F1FB", "load_balancer": "#E8F1FB",
             "firewall": "#FBE9E0", "waf": "#FBE9E0", "vpn": "#FBE9E0",
             "identity_provider": "#E9F5E4", "secrets_store": "#E9F5E4", "monitoring": "#E7EAF2"}
TYPE_SHAPE = {"database": "cylinder", "secrets_store": "cylinder", "actor": "pill",
              "firewall": "hexagon", "waf": "hexagon", "vpn": "hexagon"}
TYPE_NAME = {"waf": "WAF", "vpn": "VPN"}
HEX_INSET = 16
DEFAULT_FILL = "#EAF0F6"
STATUS_BORDER = {"confirmed": BLUE, "inferred": AMBER, "unknown": RED}
# Interactions the sender does not wait for are drawn dashed.
DASHED_KINDS = {"asynchronous", "event", "batch", "file_transfer"}
LEGEND_BASE = ["Border: blue = stated, amber = inferred, red = unknown",
               "Solid arrow = direct request or data access",
               "Dashed arrow = message, event, file or scheduled job"]

# Layout sizes in drawing units. 100 units = 1 inch in PowerPoint.
BOX_W, BOX_H, GAP_X, GAP_Y, LANE_H, MARGIN = 224, 118, 172, 34, 26, 28
LABEL_CHARS = 19  # label lines stay narrower than the gap, so the arrow shows on both sides
HEADER_H = 58
ZONE_HEAD, ZONE_PAD = 34, 14


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def status_of(obj):
    st = obj.get("evidence_status", "unknown")
    return st if st in STATUS_BORDER else "unknown"


def status_label(obj):
    st = status_of(obj)
    return "" if st == "confirmed" else f" [{st.upper()}]"


def type_label(comp):
    kind = clean(comp.get("type") or "component")
    return TYPE_NAME.get(kind, kind.replace("_", " ").title())


def legend_parts(scene):
    parts = list(LEGEND_BASE)
    if any(a["encrypted"] for a in scene["arrows"]):
        parts.append("Teal arrow = encrypted")
    if any(a["blocked"] for a in scene["arrows"]):
        parts.append("Red arrow = blocked")
    if scene["zones"]:
        parts.append("Dashed frame = zone")
    return parts


def legend_lines(scene, width):
    """Pack the legend into as few lines as fit the picture width."""
    room, lines = max(40, int((width - 2 * MARGIN) / 5.4)), []
    for part in legend_parts(scene):
        if lines and len(lines[-1]) + len(part) + 7 <= room:
            lines[-1] += "   |   " + part
        else:
            lines.append(part)
    return lines


def footer_height(scene, width):
    return 20 + 14 * len(legend_lines(scene, width))


def flow_columns(ids, links):
    """Give each id a column that follows the arrows. links are (from, to) pairs.

    Returns the column of every id and the indexes of links that close a loop
    (those are laid out backwards, then drawn pointing the right way).
    """
    out = {i: [] for i in ids}
    for k, (u, v) in enumerate(links):
        out[u].append(k)
    state, flipped = {}, set()

    def visit(u):
        state[u] = 1
        for k in out[u]:
            v = links[k][1]
            if state.get(v) == 1:
                flipped.add(k)
            elif v not in state:
                visit(v)
        state[u] = 2

    for i in ids:
        if i not in state:
            visit(i)
    pairs = [(v, u) if k in flipped else (u, v) for k, (u, v) in enumerate(links)]
    col = {i: 0 for i in ids}
    for _ in ids:  # column = longest chain of arrows leading to the box
        changed = False
        for u, v in pairs:
            if col[v] < col[u] + 1:
                col[v] = col[u] + 1
                changed = True
        if not changed:
            break
    succ = {i: [] for i in ids}
    pred = {i: [] for i in ids}
    for u, v in pairs:
        succ[u].append(v)
        pred[v].append(u)
    for i in ids:  # a box nothing points to sits right before what it points to
        if not pred[i] and succ[i]:
            col[i] = min(col[v] for v in succ[i]) - 1
    used = sorted(set(col.values()))
    return {i: used.index(c) for i, c in col.items()}, flipped


def wrap(text, width, max_lines):
    width = max(4, int(width))
    lines = textwrap.wrap(clean(text), width) or []
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1] if len(lines[-1]) < width else lines[-1][:width - 1].rstrip()
        lines[-1] = last + "…"
    return lines


def load_views(model):
    comps = {c["id"]: c for c in model.get("components", [])}
    conns = {e["id"]: e for e in model.get("connections", [])}
    views = model.get("diagrams") or [{"id": "overview", "title": model.get("title", "Architecture Overview"),
                                       "type": "overview", "component_ids": list(comps), "connection_ids": list(conns)}]
    out = []
    for v in views:
        cids = v.get("component_ids") or list(comps)
        eids = v.get("connection_ids") or list(conns)
        out.append((v, [comps[x] for x in cids if x in comps], [conns[x] for x in eids if x in conns]))
    return out


# --------------------------------------------------------------------------- layout

def build_scene(comps, conns, zone_defs=None, show_zones=True):
    """Place boxes in columns that follow the arrows, keep each zone together, and route every arrow."""
    ids = [c["id"] for c in comps]
    idset = set(ids)
    edges = [e for e in conns if e.get("from") in idset and e.get("to") in idset and e["from"] != e["to"]]
    links = [(e["from"], e["to"]) for e in edges]

    # 1. Zones. Each zone gets its own run of columns, so its frame never overlaps another.
    zone_info = {}
    for z in zone_defs or []:
        for key in (z.get("id"), z.get("name")):
            if key:
                zone_info[clean(key).lower()] = z
    zone_of = {c["id"]: (clean(c.get("boundary")).lower() or None) if show_zones else None for c in comps}
    natural, _ = flow_columns(ids, links)
    groups = []
    for i in ids:
        if zone_of[i] not in groups:
            groups.append(zone_of[i])
    members = {g: [i for i in ids if zone_of[i] == g] for g in groups}
    first = {g: n for n, g in enumerate(groups)}
    groups.sort(key=lambda g: (sum(natural[i] for i in members[g]) / len(members[g]), first[g]))
    listed = [clean(z.get("id") or z.get("name")).lower() for z in zone_defs or []]
    slots = [n for n, g in enumerate(groups) if g in listed]  # zones named in the model keep that order
    for n, g in zip(slots, sorted((groups[n] for n in slots), key=listed.index)):
        groups[n] = g

    # 2. Columns: inside a zone follow the arrows; zones follow each other left to right.
    col, flipped, span, start = {}, set(), {}, 0
    for g in groups:
        inside = [k for k, (u, v) in enumerate(links) if zone_of[u] == g and zone_of[v] == g]
        local, loops = flow_columns(members[g], [links[k] for k in inside])
        flipped |= {inside[j] for j in loops}
        for i in members[g]:
            col[i] = start + local[i]
        width = max(local.values()) + 1
        span[g] = (start, start + width - 1)
        start += width
    for k, (u, v) in enumerate(links):
        if zone_of[u] != zone_of[v] and col[u] > col[v]:
            flipped.add(k)
    pairs = [(v, u) if k in flipped else (u, v) for k, (u, v) in enumerate(links)]
    n_cols = start or 1

    # 3. Arrows that skip columns get a lane of their own in each column they pass.
    cols = [[] for _ in range(n_cols)]
    for i in ids:
        cols[col[i]].append(i)
    chains = []
    for k, (u, v) in enumerate(pairs):
        chain = [u]
        for c in range(col[u] + 1, col[v]):
            lane = ("lane", k, c)
            cols[c].append(lane)
            chain.append(lane)
        chain.append(v)
        chains.append(chain)

    # 4. Order each column so arrows cross as little as possible.
    before, after = {}, {}
    for chain in chains:
        for a, b in zip(chain, chain[1:]):
            after.setdefault(a, []).append(b)
            before.setdefault(b, []).append(a)
    for sweep in range(6):
        forward = sweep % 2 == 0
        for c in (range(1, n_cols) if forward else range(n_cols - 2, -1, -1)):
            ref = {n: i for i, n in enumerate(cols[c - 1] if forward else cols[c + 1])}
            cur = {n: i for i, n in enumerate(cols[c])}
            near = before if forward else after

            def weight(n):
                at = [ref[m] for m in near.get(n, []) if m in ref]
                return (sum(at) / len(at) if at else cur[n], cur[n])

            cols[c].sort(key=weight)

    # 5. Coordinates.
    def height(n):
        return LANE_H if isinstance(n, tuple) else BOX_H

    col_h = [sum(height(n) for n in c) + GAP_Y * (len(c) - 1) for c in cols]
    inner_h = max(col_h + [BOX_H])
    width = 2 * MARGIN + n_cols * BOX_W + (n_cols - 1) * GAP_X
    named = [g for g in groups if g]
    top = MARGIN + (ZONE_HEAD if named else 0)
    total_h = top + inner_h + MARGIN
    pos = {}
    for c, col_members in enumerate(cols):
        x = MARGIN + c * (BOX_W + GAP_X)
        y = top + (inner_h - col_h[c]) / 2
        for n in col_members:
            pos[n] = (x, y, height(n))
            y += height(n) + GAP_Y

    def mid_y(n):
        return pos[n][1] + pos[n][2] / 2

    # 6. Spread arrows along the side of a box so they do not sit on top of each other.
    leaving, entering = {}, {}
    for k, chain in enumerate(chains):
        leaving.setdefault(chain[0], []).append(k)
        entering.setdefault(chain[-1], []).append(k)
    port = {}
    for side, table, other in (("out", leaving, 1), ("in", entering, -2)):
        for n, ks in table.items():
            ks.sort(key=lambda k: mid_y(chains[k][other]))
            for j, k in enumerate(ks):
                frac = 0.5 if len(ks) == 1 else 0.22 + 0.56 * j / (len(ks) - 1)
                port[(side, k)] = frac

    zones = []
    for g in named:
        z = zone_info.get(g, {})
        label = clean(z.get("name")) or next(clean(c.get("boundary")) for c in comps if zone_of[c["id"]] == g)
        if label == label.lower():
            label = label.replace("_", " ").replace("-", " ").title()
        x0 = MARGIN + span[g][0] * (BOX_W + GAP_X) - ZONE_PAD
        x1 = MARGIN + span[g][1] * (BOX_W + GAP_X) + BOX_W + ZONE_PAD
        zones.append({"id": g, "name": label, "title": (wrap(label, (x1 - x0 - 24) / 7.2, 1) or [""])[0],
                      "description": clean(z.get("description")), "members": members[g],
                      "x": x0, "y": 8, "w": x1 - x0, "h": total_h - 16})

    boxes, shape_of = [], {}
    for c in comps:
        x, y, _ = pos[c["id"]]
        shape = TYPE_SHAPE.get(c.get("type"), "box")
        shape_of[c["id"]] = shape
        name_room = 20 if shape == "hexagon" else 23
        long_name = len(clean(c.get("name"))) > name_room
        name_lines = wrap(c.get("name"), name_room + 3 if long_name else name_room, 2 if long_name else 1)
        desc_lines = wrap(c.get("description"), 28 if shape == "hexagon" else 33,
                          2 if (len(name_lines) > 1 or shape == "cylinder") else 3)
        st = status_of(c)
        boxes.append({"id": c["id"], "x": x, "y": y, "w": BOX_W, "h": BOX_H, "shape": shape, "zone": zone_of[c["id"]],
                      "fill": TYPE_FILL.get(c.get("type"), DEFAULT_FILL), "border": STATUS_BORDER[st],
                      "name": clean(c.get("name")), "name_lines": name_lines, "name_size": 13 if long_name else 15,
                      "type_line": type_label(c) + ("" if st == "confirmed" else " · " + st.upper()),
                      "desc": clean(c.get("description")), "desc_lines": desc_lines, "tag": status_label(c)})

    def side_inset(node, frac):  # a hexagon's sides slope inwards away from the middle
        return HEX_INSET * abs(frac - 0.5) * 2 if shape_of.get(node) == "hexagon" else 0

    arrows = []
    for k, e in enumerate(edges):
        chain = chains[k]
        x0, y0, _ = pos[chain[0]]
        x1, y1, _ = pos[chain[-1]]
        pts = [(x0 + BOX_W - side_inset(chain[0], port[("out", k)]), y0 + BOX_H * port[("out", k)])]
        for lane in chain[1:-1]:
            pts += [(pos[lane][0], mid_y(lane)), (pos[lane][0] + BOX_W, mid_y(lane))]
        pts.append((x1 + side_inset(chain[-1], port[("in", k)]), y1 + BOX_H * port[("in", k)]))
        seg = 2 * ((len(pts) // 2) // 2)  # the gap nearest the middle of the arrow
        blocked, encrypted = bool(e.get("blocked")), bool(e.get("encrypted"))
        color = RED if blocked else TEAL if encrypted else GREY
        detail = " · ".join(x for x in (" ".join(clean(e.get(f)) for f in ("protocol", "port") if e.get(f)),
                                        "encrypted" if encrypted else "", "BLOCKED" if blocked else "") if x)
        lines = [(s, NAVY) for s in wrap(f"{k + 1}. {clean(e.get('label'))}", LABEL_CHARS, 3)]
        lines += [(s, color) for s in wrap(detail, LABEL_CHARS, 2)]
        # Sit the label where the arrows are furthest apart: near the end that fans out most.
        fan_out, fan_in = len(leaving[chain[0]]), len(entering[chain[-1]])
        t = 0.62 if fan_out > fan_in else 0.38 if fan_in > fan_out else 0.5
        (px, py), (qx, qy) = pts[seg], pts[seg + 1]
        label = {"x": px + (qx - px) * ((1 - t) ** 3 * 0 + 1.5 * t * (1 - t) + t ** 3),
                 "y": py + (qy - py) * (3 * t * t - 2 * t ** 3),
                 "w": max(len(s) for s, _ in lines) * 5.9 + 14, "h": len(lines) * 14 + 8, "lines": lines,
                 "gap": col[pairs[k][0]] + seg // 2}
        if k in flipped:
            pts.reverse()
        arrows.append({"id": e["id"], "from": e["from"], "to": e["to"], "n": k + 1, "pts": pts,
                       "dashed": clean(e.get("kind")).lower() in DASHED_KINDS, "label": label,
                       "text": clean(e.get("label")), "detail": detail, "color": color,
                       "blocked": blocked, "encrypted": encrypted, "flipped": k in flipped,
                       "exit": port[("in" if k in flipped else "out", k)],
                       "entry": port[("out" if k in flipped else "in", k)]})

    # 7. Labels sharing a gap are pushed apart.
    by_gap = {}
    for a in arrows:
        by_gap.setdefault(a["label"]["gap"], []).append(a["label"])
    for labels in by_gap.values():
        labels.sort(key=lambda l: l["y"])
        for prev, cur in zip(labels, labels[1:]):
            cur["y"] = max(cur["y"], prev["y"] + (prev["h"] + cur["h"]) / 2 + 4)

    return {"w": width, "h": total_h, "boxes": boxes, "arrows": arrows, "zones": zones}


def hexagon_points(b):
    x, y, w, h, i = b["x"], b["y"], b["w"], b["h"], HEX_INSET
    return [(x + i, y), (x + w - i, y), (x + w, y + h / 2), (x + w - i, y + h), (x + i, y + h), (x, y + h / 2)]


def curve_points(p, q, steps=20):
    """Points along the S-curve between two arrow points (straight when level)."""
    if abs(p[1] - q[1]) < 0.5:
        return [p, q]
    mx = (p[0] + q[0]) / 2
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        pts.append((a * p[0] + (b + c) * mx + d * q[0], (a + b) * p[1] + (c + d) * q[1]))
    return pts


def arrow_geometry(pts):
    """Return the arrow's points with the tip shortened, plus the arrowhead triangle."""
    dx = 1 if pts[-1][0] >= pts[-2][0] else -1
    tip = pts[-1]
    body = pts[:-1] + [(tip[0] - dx * 9, tip[1])]
    head = [tip, (tip[0] - dx * 12, tip[1] - 5.5), (tip[0] - dx * 12, tip[1] + 5.5)]
    return body, head


def text_rows(box):
    """(text, x, baseline y, size, bold, color) for every line inside a box."""
    x = box["x"] + {"pill": 22, "hexagon": 26}.get(box["shape"], 14)
    y = box["y"] + (8 if box["shape"] == "cylinder" else 0)
    rows = []
    if len(box["name_lines"]) > 1:
        rows += [(s, x, y + 23 + i * 16, 13, True, NAVY) for i, s in enumerate(box["name_lines"])]
        type_y = y + 57
    else:
        rows += [(s, x, y + 27, 15, True, NAVY) for s in box["name_lines"]]
        type_y = y + 46
    rows.append((box["type_line"], x, type_y, 11, False, GREY))
    rows += [(s, x, type_y + 19 + i * 14, 11, False, TEXT) for i, s in enumerate(box["desc_lines"])]
    return rows


# --------------------------------------------------------------------------- SVG

def render_svg(scene, title):
    W = max(scene["w"], 760)
    H = HEADER_H + scene["h"] + footer_height(scene, W)
    ox = (W - scene["w"]) / 2
    e = html.escape
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="Aptos,Arial,sans-serif">',
         f'<rect width="100%" height="100%" fill="{CANVAS}"/>',
         f'<text x="{MARGIN}" y="38" font-size="22" font-weight="700" fill="{NAVY}">{e(title)}</text>',
         f'<g transform="translate({ox:.1f},{HEADER_H})">']
    for z in scene["zones"]:
        s.append(f'<rect x="{z["x"]}" y="{z["y"]}" width="{z["w"]}" height="{z["h"]}" rx="3" fill="{WHITE}" stroke="{ZONE_LINE}" stroke-width="1.5" stroke-dasharray="8 5"/>')
        s.append(f'<text x="{z["x"] + 12}" y="{z["y"] + 22}" font-size="13" font-weight="700" fill="{GREY}">{e(z["title"])}</text>')
    for a in scene["arrows"]:
        body, head = arrow_geometry(a["pts"])
        d = f'M{body[0][0]:.1f},{body[0][1]:.1f}'
        for p, q in zip(body, body[1:]):
            if abs(p[1] - q[1]) < 0.5:
                d += f' L{q[0]:.1f},{q[1]:.1f}'
            else:
                mx = (p[0] + q[0]) / 2
                d += f' C{mx:.1f},{p[1]:.1f} {mx:.1f},{q[1]:.1f} {q[0]:.1f},{q[1]:.1f}'
        dash = ' stroke-dasharray="7 5"' if a["dashed"] else ''
        s.append(f'<path d="{d}" fill="none" stroke="{a["color"]}" stroke-width="2"{dash}/>')
        s.append('<polygon points="' + ' '.join(f'{x:.1f},{y:.1f}' for x, y in head) + f'" fill="{a["color"]}"/>')
    for b in scene["boxes"]:
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        if b["shape"] == "cylinder":
            r = 9
            s.append(f'<path d="M{x},{y + r} A{w / 2},{r} 0 0 1 {x + w},{y + r} V{y + h - r} A{w / 2},{r} 0 0 1 {x},{y + h - r} Z" fill="{b["fill"]}" stroke="{b["border"]}" stroke-width="2"/>')
            s.append(f'<path d="M{x},{y + r} A{w / 2},{r} 0 0 0 {x + w},{y + r}" fill="none" stroke="{b["border"]}" stroke-width="2"/>')
        elif b["shape"] == "hexagon":
            s.append('<polygon points="' + ' '.join(f'{px:.1f},{py:.1f}' for px, py in hexagon_points(b)) + f'" fill="{b["fill"]}" stroke="{b["border"]}" stroke-width="2" stroke-linejoin="round"/>')
        else:
            rx = 30 if b["shape"] == "pill" else 10
            s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{b["fill"]}" stroke="{b["border"]}" stroke-width="2"/>')
        for text, tx, ty, size, bold, color in text_rows(b):
            weight = ' font-weight="700"' if bold else ''
            s.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{size}"{weight} fill="{color}">{e(text)}</text>')
    for a in scene["arrows"]:
        l = a["label"]
        s.append(f'<rect x="{l["x"] - l["w"] / 2:.1f}" y="{l["y"] - l["h"] / 2:.1f}" width="{l["w"]:.1f}" height="{l["h"]}" rx="5" fill="{WHITE}" stroke="#C3CDD8" stroke-width="1"/>')
        for i, (line, color) in enumerate(l["lines"]):
            s.append(f'<text x="{l["x"]:.1f}" y="{l["y"] - l["h"] / 2 + 15 + i * 14:.1f}" font-size="11" text-anchor="middle" fill="{color}">{e(line)}</text>')
    s.append('</g>')
    legend = legend_lines(scene, W)
    for i, line in enumerate(legend):
        s.append(f'<text x="{MARGIN}" y="{H - 13 - 14 * (len(legend) - 1 - i)}" font-size="10.5" fill="{GREY}">{e(line)}</text>')
    s.append('</svg>')
    return '\n'.join(s)


# --------------------------------------------------------------------------- PNG

_FONTS = {}


def _font(size, bold):
    from PIL import ImageFont
    key = (round(size), bold)
    if key not in _FONTS:
        names = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else \
                ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
        for name in names:
            try:
                _FONTS[key] = ImageFont.truetype(name, key[0])
                break
            except OSError:
                continue
        else:
            _FONTS[key] = ImageFont.load_default(key[0])
    return _FONTS[key]


def render_png(scene, title, path, k=2):
    """Draw the same picture as the SVG with Pillow, so Word can embed it without extra tools."""
    from PIL import Image, ImageDraw
    W = max(scene["w"], 760)
    H = HEADER_H + scene["h"] + footer_height(scene, W)
    ox, oy = (W - scene["w"]) / 2, HEADER_H
    img = Image.new("RGB", (int(W * k), int(H * k)), CANVAS)
    d = ImageDraw.Draw(img)

    def P(x, y):
        return ((x + ox) * k, (y + oy) * k)

    def write(text, x, y, size, bold, color, anchor="ls", local=True):
        xy = P(x, y) if local else (x * k, y * k)
        d.text(xy, text, font=_font(size * k, bold), fill=color, anchor=anchor)

    def dashes(points, color, width, on, off):
        carry, draw_on = 0.0, True
        for p, q in zip(points, points[1:]):
            seg = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
            at = 0.0
            while seg - at > 1e-6:
                step = min((on if draw_on else off) - carry, seg - at)
                if draw_on:
                    a0, a1 = at / seg, (at + step) / seg
                    d.line([(p[0] + (q[0] - p[0]) * a0, p[1] + (q[1] - p[1]) * a0),
                            (p[0] + (q[0] - p[0]) * a1, p[1] + (q[1] - p[1]) * a1)], fill=color, width=width)
                at += step
                carry += step
                if carry >= (on if draw_on else off) - 1e-6:
                    carry, draw_on = 0.0, not draw_on

    write(title, MARGIN, 38, 22, True, NAVY, local=False)
    for z in scene["zones"]:
        x, y, w, h = z["x"], z["y"], z["w"], z["h"]
        d.rectangle([P(x, y), P(x + w, y + h)], fill=WHITE)
        dashes([P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h), P(x, y)], ZONE_LINE, round(1.5 * k), 8 * k, 5 * k)
        write(z["title"], x + 12, y + 22, 13, True, GREY)
    for a in scene["arrows"]:
        body, head = arrow_geometry(a["pts"])
        line = []
        for p, q in zip(body, body[1:]):
            line += curve_points(p, q)
        line = [P(*p) for p in line]
        if a["dashed"]:
            dashes(line, a["color"], 2 * k, 7 * k, 5 * k)
        else:
            d.line(line, fill=a["color"], width=2 * k, joint="curve")
        d.polygon([P(*p) for p in head], fill=a["color"])
    for b in scene["boxes"]:
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        if b["shape"] == "cylinder":
            r = 9
            d.ellipse([P(x, y + h - 2 * r), P(x + w, y + h)], fill=b["fill"], outline=b["border"], width=2 * k)
            d.rectangle([P(x, y + r), P(x + w, y + h - r)], fill=b["fill"])
            d.line([P(x, y + r), P(x, y + h - r)], fill=b["border"], width=2 * k)
            d.line([P(x + w - 1, y + r), P(x + w - 1, y + h - r)], fill=b["border"], width=2 * k)
            d.ellipse([P(x, y), P(x + w, y + 2 * r)], fill=b["fill"], outline=b["border"], width=2 * k)
        elif b["shape"] == "hexagon":
            d.polygon([P(*p) for p in hexagon_points(b)], fill=b["fill"], outline=b["border"], width=2 * k)
        else:
            d.rounded_rectangle([P(x, y), P(x + w, y + h)], radius=(30 if b["shape"] == "pill" else 10) * k,
                                fill=b["fill"], outline=b["border"], width=2 * k)
        for text, tx, ty, size, bold, color in text_rows(b):
            write(text, tx, ty, size, bold, color)
    for a in scene["arrows"]:
        l = a["label"]
        d.rounded_rectangle([P(l["x"] - l["w"] / 2, l["y"] - l["h"] / 2), P(l["x"] + l["w"] / 2, l["y"] + l["h"] / 2)],
                            radius=5 * k, fill=WHITE, outline="#C3CDD8", width=k)
        for i, (line, color) in enumerate(l["lines"]):
            write(line, l["x"], l["y"] - l["h"] / 2 + 15 + i * 14, 11, False, color, anchor="ms")
    legend = legend_lines(scene, W)
    for i, line in enumerate(legend):
        write(line, MARGIN, H - 13 - 14 * (len(legend) - 1 - i), 10.5, False, GREY, local=False)
    img.save(path)


# --------------------------------------------------------------------------- PowerPoint

def make_pptx(model, views, scenes, path):
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.dml import MSO_LINE
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn

    def rgb(hex_color):
        return RGBColor.from_string(hex_color.lstrip("#"))

    def textbox(slide, x, y, w, h, text, size, bold=False, color=NAVY):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tb.text_frame.word_wrap = True
        p = tb.text_frame.paragraphs[0]
        p.text = text
        p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = rgb(color)
        return tb

    def new_slide(title=None):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb(CANVAS)
        if title:
            textbox(slide, Inches(.45), Inches(.22), Inches(12.4), Inches(.6), title, 23, True)
        return slide

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    cover = new_slide()
    band = cover.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(1.05))
    band.fill.solid(); band.fill.fore_color.rgb = rgb(NAVY); band.line.fill.background()
    textbox(cover, Inches(.65), Inches(1.75), Inches(12), Inches(1.2), model.get("title", "Architecture Overview"), 30, True)
    textbox(cover, Inches(.68), Inches(2.85), Inches(11.8), Inches(.65), model.get("subtitle", "Architecture"), 17, color=GREY)
    textbox(cover, Inches(.68), Inches(3.8), Inches(11.7), Inches(2.2), model.get("summary", "Architecture drawn from a written description."), 16)
    textbox(cover, Inches(.68), Inches(6.85), Inches(11.8), Inches(.3), "Generated from a shared architecture model · Every shape, arrow and label is editable", 9, color=GREY)

    area_x, area_y, area_w, area_h = Inches(.45), Inches(1.0), Inches(12.43), Inches(5.75)
    for (view, comps, conns), scene in zip(views, scenes):
        slide = new_slide(view.get("title", "Architecture view"))
        s = min(area_w / (scene["w"] * 9144), area_h / (scene["h"] * 9144), 1.2)
        ox = area_x + (area_w - scene["w"] * 9144 * s) / 2
        oy = area_y + (area_h - scene["h"] * 9144 * s) / 2

        def X(v): return Emu(int(ox + v * 9144 * s))
        def Y(v): return Emu(int(oy + v * 9144 * s))
        def L(v): return Emu(int(v * 9144 * s))
        def F(pt): return Pt(max(6, round(pt * s, 1)))

        for z in scene["zones"]:  # zone frames at the back
            frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, X(z["x"]), Y(z["y"]), L(z["w"]), L(z["h"]))
            frame.adjustments[0] = 0.03
            frame.fill.solid(); frame.fill.fore_color.rgb = rgb(WHITE)
            frame.line.color.rgb = rgb(ZONE_LINE); frame.line.width = Pt(1.25); frame.line.dash_style = MSO_LINE.DASH
            tf = frame.text_frame
            tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.TOP
            tf.margin_left = L(12); tf.margin_top = L(8)
            p = tf.paragraphs[0]
            p.text = z["name"]; p.alignment = PP_ALIGN.LEFT
            p.font.size = F(10); p.font.bold = True; p.font.color.rgb = rgb(GREY)
        for a in scene["arrows"]:  # arrows next, so boxes sit on top
            pts = a["pts"]
            for i, (p, q) in enumerate(zip(pts, pts[1:])):
                line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, X(p[0]), Y(p[1]), X(q[0]), Y(q[1]))
                line.line.color.rgb = rgb(a["color"])
                line.line.width = Pt(1.75)
                if a["dashed"]:
                    line.line.dash_style = MSO_LINE.DASH
                if i == len(pts) - 2:
                    ln = line.line._get_or_add_ln()
                    ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
        for b in scene["boxes"]:
            kind = {"cylinder": MSO_SHAPE.CAN, "hexagon": MSO_SHAPE.HEXAGON}.get(b["shape"], MSO_SHAPE.ROUNDED_RECTANGLE)
            shape = slide.shapes.add_shape(kind, X(b["x"]), Y(b["y"]), L(b["w"]), L(b["h"]))
            if b["shape"] != "cylinder":
                shape.adjustments[0] = {"pill": 0.5, "hexagon": HEX_INSET / BOX_H}.get(b["shape"], 0.09)
            shape.fill.solid(); shape.fill.fore_color.rgb = rgb(b["fill"])
            shape.line.color.rgb = rgb(b["border"]); shape.line.width = Pt(1.5)
            tf = shape.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = L(10); tf.margin_top = tf.margin_bottom = L(4)
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            rows = [(b["name"] + b["tag"], 12, True, NAVY), (b["type_line"].split(" · ")[0], 8, False, BLUE)]
            if b["desc"]:
                rows.append((b["desc"], 9, False, TEXT))
            for i, (text, size, bold, color) in enumerate(rows):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = text; p.alignment = PP_ALIGN.CENTER
                p.font.size = F(size); p.font.bold = bold; p.font.color.rgb = rgb(color)
        for a in scene["arrows"]:
            l = a["label"]
            tb = slide.shapes.add_textbox(X(l["x"] - l["w"] / 2), Y(l["y"] - l["h"] / 2), L(l["w"]), L(l["h"]))
            tb.fill.solid(); tb.fill.fore_color.rgb = rgb(WHITE)
            tb.line.color.rgb = rgb("#C3CDD8"); tb.line.width = Pt(.75)
            tf = tb.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = L(4); tf.margin_top = tf.margin_bottom = L(2)
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = tf.paragraphs[0]
            p.text = f'{a["n"]}. {a["text"]}'; p.alignment = PP_ALIGN.CENTER
            p.font.size = F(8); p.font.color.rgb = rgb(NAVY)
            if a["detail"]:
                p = tf.add_paragraph()
                p.text = a["detail"]; p.alignment = PP_ALIGN.CENTER
                p.font.size = F(8); p.font.color.rgb = rgb(a["color"])
        textbox(slide, Inches(.45), Inches(6.9), Inches(12.4), Inches(.3), "   |   ".join(legend_parts(scene)), 9, color=GREY)

    notes = [("What was assumed", model.get("assumptions") or []), ("What is still unknown", model.get("open_questions") or [])]
    if any(items for _, items in notes):
        slide = new_slide("Assumptions and open questions")
        top = Inches(1.1)
        for heading, items in notes:
            textbox(slide, Inches(.65), top, Inches(12), Inches(.4), heading, 16, True)
            body = textbox(slide, Inches(.65), top + Inches(.45), Inches(12), Inches(2.3), "", 13, color=TEXT)
            for i, item in enumerate(items or ["None recorded."]):
                p = body.text_frame.paragraphs[0] if i == 0 else body.text_frame.add_paragraph()
                p.text = "•  " + clean(item)
                p.font.size = Pt(13); p.font.color.rgb = rgb(TEXT); p.space_after = Pt(6)
            top += Inches(2.85)
    prs.save(path)


# --------------------------------------------------------------------------- Draw.io

def make_drawio(model, views, scenes, path):
    mx = Element("mxfile", {"host": "app.diagrams.net", "agent": "Architecture Visualizer", "version": "24.7.17", "type": "device"})
    for vi, ((view, comps, conns), scene) in enumerate(zip(views, scenes)):
        diagram = SubElement(mx, "diagram", {"id": str(view.get("id", f"page-{vi}")), "name": clean(view.get("title", f"Architecture {vi + 1}"))})
        W, H = int(scene["w"]), int(scene["h"] + 110)
        gm = SubElement(diagram, "mxGraphModel", {"dx": "1200", "dy": "800", "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1",
                                                  "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1",
                                                  "pageWidth": str(max(W, 1100)), "pageHeight": str(max(H, 700)), "math": "0", "shadow": "0"})
        root = SubElement(gm, "root")
        SubElement(root, "mxCell", {"id": "0"})
        SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        oy = 50

        def text_cell(cid, value, x, y, w, h, style, parent="1"):
            cell = SubElement(root, "mxCell", {"id": cid, "value": value, "style": style, "vertex": "1", "parent": parent})
            SubElement(cell, "mxGeometry", {"x": str(int(x)), "y": str(int(y)), "width": str(int(w)), "height": str(int(h)), "as": "geometry"})

        text_cell("title", html.escape(clean(view.get("title", ""))), MARGIN, 4, max(W - 2 * MARGIN, 600), 36,
                  f"text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=20;fontStyle=1;fontColor={NAVY};")
        frames = {}
        for n, z in enumerate(scene["zones"]):  # a zone is a container: moving it moves its parts
            frames[z["id"]] = (f"z_{n}", z["x"], z["y"] + oy)
            text_cell(f"z_{n}", html.escape(z["name"]), z["x"], z["y"] + oy, z["w"], z["h"],
                      f"rounded=1;arcSize=3;container=1;collapsible=0;dashed=1;dashPattern=8 5;html=1;whiteSpace=wrap;fillColor={WHITE};"
                      f"strokeColor={ZONE_LINE};strokeWidth=1.5;verticalAlign=top;align=left;spacingLeft=12;spacingTop=4;"
                      f"fontSize=13;fontStyle=1;fontColor={GREY};")
        for b in scene["boxes"]:
            parent, px, py = frames.get(b["zone"], ("1", 0, 0))
            value = f'<b>{html.escape(b["name"] + b["tag"])}</b><br><font style="font-size:10px" color="{GREY}">{html.escape(b["type_line"].split(" · ")[0])}</font>'
            if b["desc"]:
                value += f'<br><font style="font-size:11px" color="{TEXT}">{html.escape(b["desc"])}</font>'
            look = {"cylinder": "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;", "pill": "rounded=1;arcSize=50;",
                    "hexagon": f"shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1;size={HEX_INSET};"}.get(b["shape"], "rounded=1;arcSize=12;")
            text_cell("n_" + b["id"], value, b["x"] - px, b["y"] + oy - py, b["w"], b["h"],
                      look + f'whiteSpace=wrap;html=1;fillColor={b["fill"]};strokeColor={b["border"]};strokeWidth=2;fontColor={NAVY};fontSize=14;align=center;verticalAlign=middle;spacing=6;',
                      parent)
        for a in scene["arrows"]:
            side = (0, 1) if a["flipped"] else (1, 0)
            style = (f'html=1;rounded=1;curved=1;endArrow=block;endFill=1;strokeColor={a["color"]};strokeWidth=2;fontSize=11;fontColor={NAVY};'
                     f'labelBackgroundColor={WHITE};exitX={side[0]};exitY={a["exit"]:.2f};exitDx=0;exitDy=0;'
                     f'entryX={side[1]};entryY={a["entry"]:.2f};entryDx=0;entryDy=0;' + ("dashed=1;dashPattern=6 4;" if a["dashed"] else ""))
            value = html.escape(f'{a["n"]}. {a["text"]}')
            if a["detail"]:
                value += f'<br><font color="{a["color"]}">{html.escape(a["detail"])}</font>'
            edge = SubElement(root, "mxCell", {"id": "e_" + a["id"], "value": value, "style": style,
                                               "edge": "1", "parent": "1", "source": "n_" + a["from"], "target": "n_" + a["to"]})
            geo = SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
            if len(a["pts"]) > 2:
                arr = SubElement(geo, "Array", {"as": "points"})
                for x, y in a["pts"][1:-1]:
                    SubElement(arr, "mxPoint", {"x": str(int(x)), "y": str(int(y + oy))})
        text_cell("legend", html.escape("   |   ".join(legend_parts(scene))), MARGIN, scene["h"] + oy + 10, max(W - 2 * MARGIN, 900), 24,
                  f"text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=10;fontColor={GREY};")
    path.write_bytes(minidom.parseString(tostring(mx, encoding="utf-8")).toprettyxml(indent="  ", encoding="utf-8"))


# --------------------------------------------------------------------------- Word

def make_docx(model, views, scenes, pngs, path):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Inches(.65)
    sec.left_margin = sec.right_margin = Inches(.8)
    doc.styles["Normal"].font.name = "Aptos"
    doc.styles["Normal"].font.size = Pt(10)
    doc.styles["Title"].font.name = "Aptos Display"
    doc.styles["Title"].font.color.rgb = RGBColor(24, 49, 83)
    by_id = {c["id"]: c for c in model.get("components", [])}

    def name_of(cid):
        return clean(by_id.get(cid, {}).get("name", cid))

    def table(headers, rows):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Light Shading Accent 1"
        for cell, text in zip(t.rows[0].cells, headers):
            cell.text = text
        for row in rows:
            for cell, text in zip(t.add_row().cells, row):
                cell.text = text

    doc.add_heading(model.get("title", "Architecture Overview"), 0)
    if model.get("subtitle"):
        doc.add_paragraph(model["subtitle"], style="Subtitle")
    if model.get("summary"):
        doc.add_heading("Summary", 1)
        doc.add_paragraph(model["summary"])
    if model.get("scope"):
        doc.add_heading("What this covers", 1)
        for x in model["scope"]:
            doc.add_paragraph(x, style="List Bullet")

    doc.add_heading("Diagrams", 1)
    for i, ((view, comps, conns), scene) in enumerate(zip(views, scenes)):
        doc.add_heading(view.get("title", f"View {i + 1}"), 2)
        if view.get("scenario"):
            doc.add_paragraph(f"Scenario: {clean(view['scenario'])}")
        if pngs[i] and pngs[i].exists():
            doc.add_picture(str(pngs[i]), width=Inches(6.9))
        else:
            doc.add_paragraph("Picture not available. See the PowerPoint or Draw.io file for this diagram.")
        for a in scene["arrows"]:
            doc.add_paragraph(f'{a["n"]}. {name_of(a["from"])} → {name_of(a["to"])}: {a["text"]}' + (f' ({a["detail"]})' if a["detail"] else ""))

    zone_names = {}
    for z in model.get("zones") or []:
        for key in (z.get("id"), z.get("name")):
            if key:
                zone_names[clean(key).lower()] = clean(z.get("name") or z.get("id"))

    def zone_name(c):
        raw = clean(c.get("boundary"))
        return zone_names.get(raw.lower(), raw)

    def link_details(e):
        return ", ".join(x for x in (" ".join(clean(e.get(f)) for f in ("protocol", "port") if e.get(f)),
                                     "encrypted" if e.get("encrypted") else "", "BLOCKED" if e.get("blocked") else "") if x)

    used_zones = []
    for c in model.get("components", []):
        if zone_name(c) and zone_name(c) not in used_zones:
            used_zones.append(zone_name(c))
    if used_zones:
        about = {clean(z.get("name") or z.get("id")): clean(z.get("description")) for z in model.get("zones") or []}
        doc.add_heading("Zones", 1)
        table(["Zone", "What it is", "Parts inside"],
              [[z, about.get(z, ""), ", ".join(clean(c.get("name")) for c in model.get("components", []) if zone_name(c) == z)]
               for z in used_zones])
    doc.add_heading("Parts of the system", 1)
    table(["Part", "Type", "Zone", "What it does", "Source", "Notes"],
          [[clean(c.get("name")), type_label(c), zone_name(c), clean(c.get("description")), status_of(c).title(),
            clean(c.get("notes") or c.get("evidence"))] for c in model.get("components", [])])
    doc.add_heading("How the parts are linked", 1)
    table(["From", "To", "What happens", "Kind", "Details", "Source"],
          [[name_of(e.get("from")), name_of(e.get("to")), clean(e.get("label")), clean(e.get("kind", "interaction")).replace("_", " "),
            link_details(e), status_of(e).title()] for e in model.get("connections", [])])
    for title, key in (("Assumptions", "assumptions"), ("Open questions", "open_questions")):
        doc.add_heading(title, 1)
        for x in model.get(key) or ["None recorded."]:
            doc.add_paragraph(x, style="List Bullet")
    doc.add_paragraph("Generated from the shared architecture model. The pictures here are for reading; "
                      "use the PowerPoint or Draw.io file to move or restyle individual shapes.")
    doc.save(path)


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("architecture-output"))
    args = ap.parse_args()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_model import validate
    errors, warnings = validate(model)
    if errors:
        raise SystemExit("Model validation failed:\n" + "\n".join(errors))

    out = args.out_dir
    pics = out / "diagrams"
    pics.mkdir(parents=True, exist_ok=True)
    views = load_views(model)
    scenes = [build_scene(comps, conns, model.get("zones"), view.get("show_zones", True)) for view, comps, conns in views]
    made, skipped = [], []

    json_out = out / "architecture.json"
    json_out.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    made.append(json_out)

    pngs = []
    for i, ((view, _, _), scene) in enumerate(zip(views, scenes), 1):
        title = clean(view.get("title") or model.get("title") or "Architecture")
        stem = f"{i:02d}-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(view.get('id', 'view')))}"
        svg = render_svg(scene, title)
        (pics / f"{stem}.svg").write_text(svg, encoding="utf-8")
        made.append(pics / f"{stem}.svg")
        if i == 1:
            (out / "architecture.svg").write_text(svg, encoding="utf-8")
            made.append(out / "architecture.svg")
        try:
            render_png(scene, title, pics / f"{stem}.png")
            pngs.append(pics / f"{stem}.png")
            made.append(pngs[-1])
        except ImportError as exc:
            pngs.append(None)
            if i == 1:
                skipped.append(f"PNG pictures (and the pictures inside Word): {exc}")

    for name, build in (("architecture.pptx", lambda p: make_pptx(model, views, scenes, p)),
                        ("architecture.drawio", lambda p: make_drawio(model, views, scenes, p)),
                        ("architecture.docx", lambda p: make_docx(model, views, scenes, pngs, p))):
        try:
            build(out / name)
            made.append(out / name)
        except ImportError as exc:
            skipped.append(f"{name}: {exc}")

    print("Generated:")
    for p in made:
        print(f" - {p}")
    if skipped:
        print("Not generated (missing Python package, run: python -m pip install -r requirements.txt):")
        for s in skipped:
            print(f" - {s}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f" - {w}")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
