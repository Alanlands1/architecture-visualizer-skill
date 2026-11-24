# GitLab Duo Architecture Visualizer

A project-level GitLab Duo Agent Skill that converts architecture write-ups into a shared JSON model and synchronized enterprise deliverables.

## Outputs

- **PPTX**: native editable PowerPoint shapes, labels, containers, and connectors (primary output).
- **Draw.io**: editable diagrams.net XML.
- **DOCX**: editable architecture document with text, tables, and embedded diagram preview.
- **JSON**: normalized architecture model used by every renderer.
- **SVG**: scalable vector overview.

## Install in a repository

Copy this directory to:

```text
<repository>/.agents/skills/architecture-visualizer/
```

Start a new GitLab Duo CLI session and invoke:

```text
/architecture-visualizer
```

Project-level Agent Skills require GitLab Duo CLI 8.73.0+ (per current GitLab documentation). The `slash-command: enabled` metadata exposes the skill as `/architecture-visualizer`.

## Dependencies

Python 3.10+ recommended.

```bash
python -m pip install -r requirements.txt
```

`python-pptx` and `python-docx` create the editable Office deliverables. The Draw.io XML and SVG generators use the Python standard library. `pypdf` and `python-pptx` are used by the optional write-up extraction utility.

## Generate from a normalized model

```bash
python scripts/validate_model.py examples/architecture.example.json
python scripts/generate.py examples/architecture.example.json --out-dir output
```

## Convert source documents to text (optional helper)

```bash
python scripts/extract_text.py path/to/architecture.pdf --out extracted.txt
python scripts/extract_text.py path/to/architecture.docx --out extracted.txt
python scripts/extract_text.py path/to/architecture.pptx --out extracted.txt
```

The skill's AI interpretation step is still responsible for creating `architecture.json` from the extracted/pasted write-up. The helper does not guess architecture relationships.

## Model contract

See `schemas/architecture.schema.json` and `examples/architecture.example.json`. IDs must be unique and all connection endpoints must reference declared components. `evidence_status` should be `confirmed`, `inferred`, or `unknown`.

## Important editability distinction

PowerPoint and Draw.io are generated as native editable diagram elements. Word content is editable; the overview diagram is embedded as SVG for scalable rendering, not promised as individual Word drawing shapes. Use the PPTX or Draw.io file when editing individual diagram elements.
