#!/usr/bin/env python3
"""Validate Architecture Visualizer JSON without third-party dependencies."""
import argparse, json, sys
from pathlib import Path

STATUSES = {"confirmed", "inferred", "unknown"}

def validate(data):
    errors, warnings = [], []
    if not isinstance(data, dict): return ["Root must be a JSON object."], []
    for key in ("title", "components", "connections"):
        if key not in data: errors.append(f"Missing required field: {key}")
    if not isinstance(data.get("components", []), list): errors.append("components must be an array")
    if not isinstance(data.get("connections", []), list): errors.append("connections must be an array")
    components = data.get("components", []) if isinstance(data.get("components", []), list) else []
    connections = data.get("connections", []) if isinstance(data.get("connections", []), list) else []
    ids = []
    for i, c in enumerate(components):
        if not isinstance(c, dict): errors.append(f"components[{i}] must be an object"); continue
        for k in ("id", "name", "type"):
            if not c.get(k): errors.append(f"components[{i}] missing {k}")
        if c.get("id") in ids: errors.append(f"Duplicate component id: {c.get('id')}")
        ids.append(c.get("id"))
        status = c.get("evidence_status", "unknown")
        if status not in STATUSES: errors.append(f"Component {c.get('id')}: invalid evidence_status {status}")
        if status != "confirmed": warnings.append(f"Component {c.get('id')} is {status}; label it clearly in diagrams.")
    conn_ids, known = [], set(ids)
    for i, e in enumerate(connections):
        if not isinstance(e, dict): errors.append(f"connections[{i}] must be an object"); continue
        for k in ("id", "from", "to", "label"):
            if not e.get(k): errors.append(f"connections[{i}] missing {k}")
        if e.get("id") in conn_ids: errors.append(f"Duplicate connection id: {e.get('id')}")
        conn_ids.append(e.get("id"))
        if e.get("from") not in known: errors.append(f"Connection {e.get('id')} has unknown source {e.get('from')}")
        if e.get("to") not in known: errors.append(f"Connection {e.get('id')} has unknown target {e.get('to')}")
        status = e.get("evidence_status", "unknown")
        if status not in STATUSES: errors.append(f"Connection {e.get('id')}: invalid evidence_status {status}")
        if status != "confirmed": warnings.append(f"Connection {e.get('id')} is {status}; label it clearly in diagrams.")
    # Text that will not fit the diagram.
    for c in components:
        if isinstance(c, dict):
            if len(str(c.get("name", ""))) > 40: warnings.append(f"Component {c.get('id')}: name is over 40 characters and will be cut short in the diagram.")
            if len(str(c.get("description", ""))) > 90: warnings.append(f"Component {c.get('id')}: description is over 90 characters and will be cut short in the diagram.")
    by_conn = {e.get("id"): e for e in connections if isinstance(e, dict)}
    for e in by_conn.values():
        if len(str(e.get("label", ""))) > 45: warnings.append(f"Connection {e.get('id')}: label is over 45 characters and will be cut short on the arrow.")
        if e.get("from") and e.get("from") == e.get("to"): warnings.append(f"Connection {e.get('id')} links {e.get('from')} to itself and will not be drawn.")
    for d in data.get("diagrams", []) or []:
        shown = set(d.get("component_ids", []))
        for cid in d.get("component_ids", []):
            if cid not in known: errors.append(f"Diagram {d.get('id')} references unknown component {cid}")
        for eid in d.get("connection_ids", []):
            if eid not in by_conn: errors.append(f"Diagram {d.get('id')} references unknown connection {eid}"); continue
            e = by_conn[eid]
            if e.get("from") not in shown or e.get("to") not in shown:
                warnings.append(f"Diagram {d.get('id')}: connection {eid} will not be drawn because one of its ends is not in this diagram.")
        if len(shown) > 8: warnings.append(f"Diagram {d.get('id')} has {len(shown)} components; more than 8 gets crowded, consider splitting it.")
    if not data.get("diagrams"): warnings.append("No diagrams declared; generator will create a default overview.")
    return errors, warnings

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("model", type=Path); args=ap.parse_args()
    try: data=json.loads(args.model.read_text(encoding="utf-8"))
    except Exception as e: print(f"ERROR: cannot read JSON: {e}"); return 2
    errors,warnings=validate(data)
    for x in errors: print("ERROR:",x)
    for x in warnings: print("WARNING:",x)
    if errors: print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s)."); return 1
    print(f"Validation passed: {len(data.get('components',[]))} components, {len(data.get('connections',[]))} connections, {len(data.get('diagrams',[]))} diagram(s).")
    return 0
if __name__ == "__main__": sys.exit(main())
