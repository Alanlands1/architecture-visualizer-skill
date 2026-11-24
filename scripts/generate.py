#!/usr/bin/env python3
"""Generate editable PPTX, Draw.io, Visio, DOCX, SVG and PNG deliverables from one architecture JSON model.

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
PANEL_W, PANEL_GAP, PANEL_HEAD = 250, 14, 28


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
                                       "type": "overview", "component_ids": list(comps), "connection_ids": list(conns),
                                       "panel_ids": [p.get("id") for p in model.get("panels") or []]}]
    out = []
    for v in views:
        cids = v.get("component_ids") or list(comps)
        eids = v.get("connection_ids") or list(conns)
        out.append((v, [comps[x] for x in cids if x in comps], [conns[x] for x in eids if x in conns]))
    return out


# --------------------------------------------------------------------------- layout

def layout_panels(panels, x0, min_h):
    """Stack the side panels in columns to the right of the diagram."""
    cards = []
    for p in panels:
        items = [clean(i) for i in p.get("items") or [] if clean(i)]
        rows = [(line, i == 0) for item in items for i, line in enumerate(wrap(item, 38, 3))]
        name = clean(p.get("title") or p.get("id"))
        cards.append({"name": name, "title": (wrap(name, 30, 1) or [""])[0], "items": items, "rows": rows,
                      "w": PANEL_W, "h": PANEL_HEAD + 12 + 14 * len(rows) + 4})
    limit = max([min_h - 16] + [c["h"] for c in cards])
    x, y = x0, 8
    for c in cards:
        if y > 8 and y + c["h"] > 8 + limit:
            x, y = x + PANEL_W + PANEL_GAP, 8
        c["x"], c["y"] = x, y
        y += c["h"] + PANEL_GAP
    return cards


def build_scene(comps, conns, zone_defs=None, show_zones=True, panels=None):
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

    def canon(key):  # one spelling per zone, whether the model used its id or its name
        key = clean(key).lower()
        z = zone_info.get(key)
        return (clean(z.get("id") or z.get("name")).lower() if z else key) or None

    parent_of = {}
    for z in zone_defs or []:
        me, up = canon(z.get("id") or z.get("name")), canon(z.get("parent"))
        seen, at = set(), up
        while at and at not in seen and at != me:
            seen.add(at)
            at = parent_of.get(at)
        if up in zone_info and at != me:
            parent_of[me] = up

    def path(g):  # the zone and the zones around it, outermost first
        out = [g]
        while parent_of.get(out[0]):
            out.insert(0, parent_of[out[0]])
        return out

    zone_of = {c["id"]: canon(c.get("boundary")) if show_zones else None for c in comps}
    natural, _ = flow_columns(ids, links)
    groups = []
    for i in ids:
        if zone_of[i] not in groups:
            groups.append(zone_of[i])
    members = {g: [i for i in ids if zone_of[i] == g] for g in groups}
    first = {g: n for n, g in enumerate(groups)}
    linked = {i for pair in links for i in pair}

    def flow_place(g):  # parts with no arrows say nothing about where their zone belongs
        cols_ = [natural[i] for i in members[g] if i in linked]
        return sum(cols_) / len(cols_) if cols_ else float("inf")

    groups.sort(key=lambda g: (flow_place(g), first[g]))
    listed = [canon(z.get("id") or z.get("name")) for z in zone_defs or []]
    slots = [n for n, g in enumerate(groups) if g in listed]  # zones named in the model keep that order
    for n, g in zip(slots, sorted((groups[n] for n in slots), key=listed.index)):
        groups[n] = g
    at = {g: n for n, g in enumerate(groups)}  # zones inside the same outer zone stay side by side

    def first(z):
        return min(at[g] for g in groups if g and z in path(g))

    order = {g: tuple(first(a) for a in path(g)) + (at[g],) if g else (at[g],) for g in groups}
    groups.sort(key=order.get)

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
    named = [g for g in groups if g]
    tree = []  # every zone that gets a frame, outer zones before the zones inside them
    for g in named:
        for a in path(g):
            if a not in tree:
                tree.append(a)
    tree.sort(key=lambda z: len(path(z)))
    levels = max((len(path(z)) for z in tree), default=0)
    left = MARGIN + ZONE_PAD * max(0, levels - 1)
    width = 2 * left + n_cols * BOX_W + (n_cols - 1) * GAP_X
    top = MARGIN + ZONE_HEAD * levels
    total_h = top + inner_h + MARGIN + ZONE_PAD * max(0, levels - 1)
    pos = {}
    for c, col_members in enumerate(cols):
        x = left + c * (BOX_W + GAP_X)
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

    def x_range(z):  # a frame wraps its own parts and the frames inside it
        lo, hi = [], []
        if z in span:
            lo.append(left + span[z][0] * (BOX_W + GAP_X) - ZONE_PAD)
            hi.append(left + span[z][1] * (BOX_W + GAP_X) + BOX_W + ZONE_PAD)
        for k in tree:
            if parent_of.get(k) == z:
                a, b = x_range(k)
                lo.append(a - ZONE_PAD)
                hi.append(b + ZONE_PAD)
        return min(lo), max(hi)

    zones = []
    for g in tree:
        z = zone_info.get(g, {})
        label = clean(z.get("name")) or next(clean(c.get("boundary")) for c in comps if zone_of[c["id"]] == g)
        if label == label.lower():
            label = label.replace("_", " ").replace("-", " ").title()
        x0, x1 = x_range(g)
        depth = len(path(g)) - 1
        y0 = 8 + depth * ZONE_HEAD
        zones.append({"id": g, "name": label, "title": (wrap(label, (x1 - x0 - 24) / 7.2, 1) or [""])[0],
                      "description": clean(z.get("description")), "members": members.get(g, []),
                      "parent": parent_of.get(g), "depth": depth,
                      "x": x0, "y": y0, "w": x1 - x0, "h": total_h - 8 - depth * ZONE_PAD - y0})

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

    cards = layout_panels(panels or [], width, total_h)
    if cards:
        width = max(c["x"] + c["w"] for c in cards) + MARGIN
        total_h = max([total_h] + [c["y"] + c["h"] + 8 for c in cards])
    return {"w": width, "h": total_h, "boxes": boxes, "arrows": arrows, "zones": zones, "panels": cards}


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
    for c in scene["panels"]:
        s.append(f'<rect x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" rx="6" fill="{NAVY}" stroke="{NAVY}" stroke-width="1.5"/>')
        s.append(f'<rect x="{c["x"] + 1}" y="{c["y"] + PANEL_HEAD}" width="{c["w"] - 2}" height="{c["h"] - PANEL_HEAD - 1}" rx="5" fill="{WHITE}"/>')
        s.append(f'<text x="{c["x"] + 12}" y="{c["y"] + 19}" font-size="12" font-weight="700" fill="{WHITE}">{e(c["title"])}</text>')
        for i, (line, lead) in enumerate(c["rows"]):
            ty = c["y"] + PANEL_HEAD + 19 + i * 14
            if lead:
                s.append(f'<text x="{c["x"] + 10}" y="{ty}" font-size="11" fill="{BLUE}">•</text>')
            s.append(f'<text x="{c["x"] + 22}" y="{ty}" font-size="11" fill="{TEXT}">{e(line)}</text>')
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
    for c in scene["panels"]:
        d.rounded_rectangle([P(c["x"], c["y"]), P(c["x"] + c["w"], c["y"] + c["h"])], radius=6 * k, fill=NAVY)
        d.rounded_rectangle([P(c["x"] + 1.5, c["y"] + PANEL_HEAD), P(c["x"] + c["w"] - 1.5, c["y"] + c["h"] - 1.5)], radius=5 * k, fill=WHITE)
        write(c["title"], c["x"] + 12, c["y"] + 19, 12, True, WHITE)
        for i, (line, lead) in enumerate(c["rows"]):
            ty = c["y"] + PANEL_HEAD + 19 + i * 14
            if lead:
                write("•", c["x"] + 10, ty, 11, False, BLUE)
            write(line, c["x"] + 22, ty, 11, False, TEXT)
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
        for c in scene["panels"]:
            for top, tall, fill, rows in ((c["y"], PANEL_HEAD, NAVY, [(c["name"], 9, True, WHITE)]),
                                          (c["y"] + PANEL_HEAD, c["h"] - PANEL_HEAD, WHITE, [("•  " + i, 8, False, TEXT) for i in c["items"]])):
                card = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, X(c["x"]), Y(top), L(c["w"]), L(tall))
                card.fill.solid(); card.fill.fore_color.rgb = rgb(fill)
                card.line.color.rgb = rgb(NAVY); card.line.width = Pt(1)
                tf = card.text_frame
                tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.TOP if fill == WHITE else MSO_ANCHOR.MIDDLE
                tf.margin_left = tf.margin_right = L(8); tf.margin_top = tf.margin_bottom = L(4)
                for i, (text, size, bold, color) in enumerate(rows):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.text = text; p.alignment = PP_ALIGN.LEFT
                    p.font.size = F(size); p.font.bold = bold; p.font.color.rgb = rgb(color)
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
        for n, z in enumerate(scene["zones"]):  # a zone is a container: moving it moves what is inside
            parent, px, py = frames.get(z["parent"], ("1", 0, 0))
            frames[z["id"]] = (f"z_{n}", z["x"], z["y"] + oy)
            text_cell(f"z_{n}", html.escape(z["name"]), z["x"] - px, z["y"] + oy - py, z["w"], z["h"],
                      f"rounded=1;arcSize=3;container=1;collapsible=0;dashed=1;dashPattern=8 5;html=1;whiteSpace=wrap;fillColor={WHITE};"
                      f"strokeColor={ZONE_LINE};strokeWidth=1.5;verticalAlign=top;align=left;spacingLeft=12;spacingTop=4;"
                      f"fontSize=13;fontStyle=1;fontColor={GREY};", parent)
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
        for n, c in enumerate(scene["panels"]):
            text_cell(f"p_{n}", html.escape(c["name"]), c["x"], c["y"] + oy, c["w"], c["h"],
                      f"swimlane;startSize={PANEL_HEAD};collapsible=0;html=1;whiteSpace=wrap;fillColor={NAVY};swimlaneFillColor={WHITE};"
                      f"strokeColor={NAVY};fontColor={WHITE};fontSize=12;fontStyle=1;align=left;spacingLeft=8;")
            text_cell(f"p_{n}_body", "<br>".join("• " + html.escape(i) for i in c["items"]), 0, PANEL_HEAD, c["w"], c["h"] - PANEL_HEAD,
                      f"text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacing=6;fontSize=11;fontColor={TEXT};",
                      f"p_{n}")
        text_cell("legend", html.escape("   |   ".join(legend_parts(scene))), MARGIN, scene["h"] + oy + 10, max(W - 2 * MARGIN, 900), 24,
                  f"text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontSize=10;fontColor={GREY};")
    path.write_bytes(minidom.parseString(tostring(mx, encoding="utf-8")).toprettyxml(indent="  ", encoding="utf-8"))


# --------------------------------------------------------------------------- Visio

VSDX_NS = "http://schemas.microsoft.com/office/visio/2012/main"
VSDX_REL = "http://schemas.microsoft.com/visio/2010/relationships/"


def make_vsdx(model, views, scenes, path):
    """Write a Visio drawing with one page per view. Needs no extra package: a .vsdx is a zip of XML."""
    import zipfile
    esc = html.escape
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    ns = f'xmlns="{VSDX_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xml:space="preserve"'

    def cell(name, value, formula=None):
        return f'<Cell N="{name}" V="{value}"' + (f' F="{formula}"' if formula else '') + '/>'

    def page_xml(scene, title):
        W = max(scene["w"], 760)
        H = HEADER_H + scene["h"] + footer_height(scene, W)
        ox = (W - scene["w"]) / 2
        out, count = [], [0]

        def shape(x, y, w, h, rows, runs, fill=None, line=None, weight=1.5, dashed=False, rounding=0, arrow=False,
                  align=1, valign=1, pad=6, local=True, extra_geometry=""):
            """x, y, w, h and row points are in drawing units with y pointing down; Visio wants inches, y up."""
            count[0] += 1
            if local:
                x, y = x + ox, y + HEADER_H
            wi, hi = max(w, 0.1) / 100, max(h, 0.1) / 100
            s = [f'<Shape ID="{count[0]}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">',
                 cell("PinX", f"{(x + w / 2) / 100:.4f}"), cell("PinY", f"{(H - y - h / 2) / 100:.4f}"),
                 cell("Width", f"{wi:.4f}"), cell("Height", f"{hi:.4f}"),
                 cell("LocPinX", f"{wi / 2:.4f}", "Width*0.5"), cell("LocPinY", f"{hi / 2:.4f}", "Height*0.5"),
                 cell("FillPattern", 1 if fill else 0), cell("FillForegnd", fill or WHITE),
                 cell("LinePattern", 0 if not line else 2 if dashed else 1), cell("LineColor", line or GREY),
                 cell("LineWeight", f"{weight / 72:.4f}"), cell("Rounding", f"{rounding / 100:.4f}"),
                 cell("EndArrow", 4 if arrow else 0), cell("EndArrowSize", 2),
                 cell("VerticalAlign", valign)]
            s += [cell(m, f"{pad / 100:.4f}") for m in ("LeftMargin", "RightMargin", "TopMargin", "BottomMargin")]
            if runs:
                s.append('<Section N="Character">')
                for i, (_, size, bold, color) in enumerate(runs):
                    s.append(f'<Row IX="{i}">' + cell("Font", "Arial") + cell("Color", color) + cell("Style", 1 if bold else 0)
                             + cell("Size", f"{size / 100:.4f}") + '</Row>')
                s.append(f'</Section><Section N="Paragraph"><Row IX="0">{cell("HorzAlign", align)}</Row></Section>')
            if rows:
                s.append(f'<Section N="Geometry" IX="0">{cell("NoFill", 0 if fill else 1)}{cell("NoLine", 0)}')
                for i, (kind, px, py, *bow) in enumerate(rows, 1):
                    lx, ly = (px - (x - ox if local else x)) / 100, (h - (py - (y - HEADER_H if local else y))) / 100
                    fx = f"Width*{lx / wi:.5f}" if w > 1 else None
                    fy = f"Height*{ly / hi:.5f}" if h > 1 else None
                    s.append(f'<Row T="{kind}" IX="{i}">' + cell("X", f"{lx:.4f}", fx) + cell("Y", f"{ly:.4f}", fy)
                             + (cell("A", f"{bow[0] / 100:.4f}") if bow else '') + '</Row>')
                s.append('</Section>' + extra_geometry)
            if runs:
                s.append('<Text><pp IX="0"/>' + '\n'.join(f'<cp IX="{i}"/>{esc(t, quote=False)}' for i, (t, *_) in enumerate(runs)) + '</Text>')
            s.append('</Shape>')
            out.append(''.join(s))

        def rect(x, y, w, h):
            return [("MoveTo", x, y + h), ("LineTo", x + w, y + h), ("LineTo", x + w, y), ("LineTo", x, y), ("LineTo", x, y + h)]

        shape(MARGIN, 10, W - 2 * MARGIN, 40, None, [(title, 22, True, NAVY)], align=0, local=False)
        for z in scene["zones"]:
            shape(z["x"], z["y"], z["w"], z["h"], rect(z["x"], z["y"], z["w"], z["h"]), [(z["name"], 13, True, GREY)],
                  fill=WHITE, line=ZONE_LINE, dashed=True, rounding=3, align=0, valign=0, pad=10)
        for a in scene["arrows"]:
            pts = []
            for p, q in zip(a["pts"], a["pts"][1:]):
                pts += curve_points(p, q, 12)[(1 if pts else 0):]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            shape(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
                  [("MoveTo" if i == 0 else "LineTo", px, py) for i, (px, py) in enumerate(pts)], None,
                  line=a["color"], weight=1.75, dashed=a["dashed"], arrow=True)
        for b in scene["boxes"]:
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            runs = [(b["name"] + b["tag"], 15, True, NAVY), (b["type_line"].split(" · ")[0], 10, False, BLUE)]
            if b["desc"]:
                runs.append((b["desc"], 11, False, TEXT))
            look = dict(fill=b["fill"], line=b["border"], pad=10)
            if b["shape"] == "cylinder":
                r = 9  # the rim is a second, unfilled outline on top of the body
                rim = (f'<Section N="Geometry" IX="1">{cell("NoFill", 1)}{cell("NoLine", 0)}'
                       f'<Row T="MoveTo" IX="1">{cell("X", 0)}{cell("Y", f"{(h - r) / 100:.4f}", f"Height-{r / 100}")}</Row>'
                       f'<Row T="ArcTo" IX="2">{cell("X", f"{w / 100:.4f}", "Width")}{cell("Y", f"{(h - r) / 100:.4f}", f"Height-{r / 100}")}{cell("A", r / 100)}</Row></Section>')
                shape(x, y, w, h, [("MoveTo", x, y + r), ("LineTo", x, y + h - r), ("ArcTo", x + w, y + h - r, r),
                                   ("LineTo", x + w, y + r), ("ArcTo", x, y + r, r)], runs, extra_geometry=rim, **look)
            elif b["shape"] == "hexagon":
                hexa = hexagon_points(b)
                shape(x, y, w, h, [("MoveTo" if i == 0 else "LineTo", px, py) for i, (px, py) in enumerate(hexa + hexa[:1])],
                      runs, **{**look, "pad": 22})
            else:
                shape(x, y, w, h, rect(x, y, w, h), runs, rounding=30 if b["shape"] == "pill" else 10, **look)
        for a in scene["arrows"]:
            l = a["label"]
            runs = [(f'{a["n"]}. {a["text"]}', 10, False, NAVY)] + ([(a["detail"], 10, False, a["color"])] if a["detail"] else [])
            x, y = l["x"] - l["w"] / 2, l["y"] - l["h"] / 2
            shape(x, y, l["w"], l["h"], rect(x, y, l["w"], l["h"]), runs, fill=WHITE, line="#C3CDD8", weight=.75, rounding=5, pad=3)
        for c in scene["panels"]:
            shape(c["x"], c["y"], c["w"], PANEL_HEAD, rect(c["x"], c["y"], c["w"], PANEL_HEAD), [(c["name"], 12, True, WHITE)],
                  fill=NAVY, line=NAVY, weight=1, align=0, pad=8)
            shape(c["x"], c["y"] + PANEL_HEAD, c["w"], c["h"] - PANEL_HEAD, rect(c["x"], c["y"] + PANEL_HEAD, c["w"], c["h"] - PANEL_HEAD),
                  [("•  " + i, 11, False, TEXT) for i in c["items"]] or None, fill=WHITE, line=NAVY, weight=1, align=0, valign=0, pad=8)
        shape(MARGIN, H - 34, W - 2 * MARGIN, 28, None, [("   |   ".join(legend_parts(scene)), 10, False, GREY)], align=0, local=False)
        return W / 100, H / 100, f'{head}<PageContents {ns}><Shapes>{"".join(out)}</Shapes></PageContents>'

    pages, names = [], []
    for i, ((view, _, _), scene) in enumerate(zip(views, scenes), 1):
        title = clean(view.get("title") or model.get("title") or f"View {i}")
        name = re.sub(r'[\\/:*?\[\]]', " ", title)[:28].strip() or f"View {i}"
        if name in names:
            name = f"{name[:25]} {i}"
        names.append(name)
        pages.append((name,) + page_xml(scene, title))

    sheet = ('<StyleSheet ID="0" NameU="No Style" Name="No Style">' + cell("LineWeight", "0.0104") + cell("LineColor", GREY)
             + cell("LinePattern", 1) + cell("FillForegnd", WHITE) + cell("FillBkgnd", WHITE) + cell("FillPattern", 1)
             + cell("VerticalAlign", 1) + '<Section N="Character"><Row IX="0">' + cell("Font", "Arial") + cell("Color", NAVY)
             + cell("Style", 0) + cell("Size", "0.1111") + '</Row></Section><Section N="Paragraph"><Row IX="0">'
             + cell("HorzAlign", 1) + '</Row></Section></StyleSheet>')
    parts = {
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
            '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
            + ''.join(f'<Override PartName="/visio/pages/page{i}.xml" ContentType="application/vnd.ms-visio.page+xml"/>'
                      for i in range(1, len(pages) + 1)) + '</Types>',
        "_rels/.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{VSDX_REL}document" Target="visio/document.xml"/></Relationships>',
        "visio/document.xml": f'{head}<VisioDocument {ns}><DocumentSettings TopPage="0" DefaultLineStyle="0" DefaultFillStyle="0" '
            f'DefaultTextStyle="0" DefaultGuideStyle="0"/><StyleSheets>{sheet}</StyleSheets></VisioDocument>',
        "visio/_rels/document.xml.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{VSDX_REL}pages" Target="pages/pages.xml"/></Relationships>',
        "visio/pages/pages.xml": f'{head}<Pages {ns}>' + ''.join(
            f'<Page ID="{i}" NameU="{esc(n)}" Name="{esc(n)}"><PageSheet LineStyle="0" FillStyle="0" TextStyle="0">'
            + cell("PageWidth", f"{w:.4f}") + cell("PageHeight", f"{h:.4f}") + cell("PageScale", 1) + cell("DrawingScale", 1)
            + cell("DrawingSizeType", 3) + cell("DrawingScaleType", 0) + f'</PageSheet><Rel r:id="rId{i + 1}"/></Page>'
            for i, (n, w, h, _) in enumerate(pages)) + '</Pages>',
        "visio/pages/_rels/pages.xml.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="rId{i}" Type="{VSDX_REL}page" Target="page{i}.xml"/>' for i in range(1, len(pages) + 1))
            + '</Relationships>',
    }
    for i, (_, _, _, xml) in enumerate(pages, 1):
        parts[f"visio/pages/page{i}.xml"] = xml
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)


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
    if model.get("panels"):
        doc.add_heading("Summary panels", 1)
        table(["Panel", "Points"], [[clean(p.get("title") or p.get("id")), "\n".join("• " + clean(i) for i in p.get("items") or [])]
                                    for p in model["panels"]])
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
    scenes = [build_scene(comps, conns, model.get("zones"), view.get("show_zones", True),
                          [p for p in model.get("panels") or [] if p.get("id") in (view.get("panel_ids") or [])])
              for view, comps, conns in views]
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
                        ("architecture.vsdx", lambda p: make_vsdx(model, views, scenes, p)),
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
