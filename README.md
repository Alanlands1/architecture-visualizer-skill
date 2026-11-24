# GitLab Duo Architecture Visualizer

A project-level GitLab Duo Agent Skill. Describe a system in plain English ("shoppers use the website, it talks to our backend, the backend saves orders and asks Stripe to take payment") and it draws the architecture diagrams for you. Written documents (PDF, DOCX, PPTX, Markdown, text) work too.

It also draws security and network architecture: zones such as Internet, DMZ, and internal networks, firewalls and other controls, and links marked as encrypted or blocked. `SKILL.md` holds the main instructions and `SECURITY-ARCHITECTURE.md` holds the security ones.

Everything is generated from one shared JSON model, so all the files below always show the same picture.

## Examples

Each example folder holds a complete run: the plain-English input in `description.md`, and every generated file in `output/`. Start with the pictures in `output/diagrams/`.

- `examples/online-bookstore/`: an ordinary application, 23 parts across five diagrams.
- `examples/secure-patient-portal/`: a security setup with five zones, firewalls, a VPN, sign-in, secrets, and logging, across four diagrams.

## Outputs

- **PPTX**: one slide per diagram, built from native editable shapes, arrows, and labels (primary output).
- **Draw.io**: one page per diagram, editable in diagrams.net.
- **Visio**: `architecture.vsdx`, one page per diagram, with editable shapes. Arrows are plain lines and do not follow a box when it is moved.
- **DOCX**: a written document with every diagram, its numbered steps, and tables of parts and links.
- **PNG and SVG**: one picture per diagram in `diagrams/`.
- **JSON**: the architecture model used by every renderer.

Diagrams are laid out automatically, left to right along the arrows. Databases are drawn as cylinders and people as rounded pills. Each arrow carries its step number and label; dashed arrows are messages, events, files, or scheduled jobs. An amber border marks a part that was inferred, not stated. Zones can sit inside other zones, and whole-system facts such as "TLS 1.2 or higher" appear as titled side panels to the right of a diagram. In security diagrams, zones are dashed frames, firewalls are hexagons, teal arrows are encrypted, and red arrows are blocked.

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

`python-pptx` and `python-docx` create the editable Office deliverables, and `Pillow` draws the PNG pictures that go into the Word document. The Draw.io, Visio and SVG generators use the Python standard library. `pypdf` is used by the optional text extraction helper.

## Generate from a normalized model

```bash
python scripts/validate_model.py examples/architecture.example.json
python scripts/generate.py examples/architecture.example.json --out-dir output
python scripts/generate.py examples/online-bookstore/output/architecture.json --out-dir my-bookstore-output
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

PowerPoint and Draw.io are generated as native editable diagram elements. In Word the text and tables are editable, but each diagram is a picture. Use the PPTX or Draw.io file when editing individual diagram elements.
