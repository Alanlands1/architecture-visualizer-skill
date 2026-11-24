---
name: architecture-visualizer
description: Convert architecture write-ups (PDF, DOCX, PPTX, Markdown, text, or pasted content) into consistent enterprise architecture models and editable PowerPoint, Draw.io, and Word deliverables. Use when a user asks to visualize, document, or update a system architecture from supplied written material.
metadata:
  slash-command: enabled
---

# Architecture Visualizer

Turn written architecture descriptions into clear, evidence-grounded architecture deliverables. PowerPoint is the primary output. Always generate PowerPoint with native editable shapes and connectors, Draw.io XML with editable cells, Word documentation with editable text/tables, and a shared JSON architecture model.

## Core rules

1. Treat the supplied write-up as the source of truth. Do not infer undocumented components, protocols, ownership, deployment locations, or data flows as facts.
2. Separate confirmed facts from assumptions and open questions. Record evidence as short source excerpts or section references when available.
3. If important details are ambiguous, ask concise clarifying questions before finalizing. If the user wants a first draft, mark uncertainty visibly instead of inventing details.
4. Keep all outputs synchronized by generating them from one `architecture.json` model. Never author each output independently.
5. Prefer a small number of readable diagrams over one crowded diagram. Split context, container/component, data flow, sequence, and deployment views when appropriate.
6. Use a professional enterprise visual system: restrained navy/blue/teal palette, light neutral canvas, consistent typography, aligned spacing, clear grouping, concise labels, and a legend. Do not rely on color alone to convey meaning.
7. Preserve original terminology and capitalization from the write-up. Expand acronyms on first use when their meaning is supplied.
8. Do not include secrets, credentials, personal data, or environment-specific values unless explicitly required and safe to include. Redact tokens and passwords.

## Supported input formats

Accept user-provided or repository-local: PDF, DOCX, PPTX, Markdown, TXT, and pasted text. Use installed parsing tools when available (for example `python-docx`, `python-pptx`, and `pypdf`). For scanned PDFs, request OCR/text or use an available OCR tool; do not silently treat an empty extraction as an empty architecture.

## Workflow

### 1. Locate and read inputs

- Identify the requested architecture write-up and any supporting files.
- Extract the complete relevant content, including tables and headings where practical.
- Record the source filename and section/page references.
- If multiple documents conflict, report the conflict and ask which source takes precedence.

### 2. Interpret the architecture

Identify, where documented:

- System purpose, scope, actors, and external systems.
- Applications, services, modules, components, and their responsibilities.
- Interfaces, APIs, protocols, events, queues, and direction of communication.
- Datastores, data ownership, read/write relationships, and data movement.
- Identity, authentication, authorization, security boundaries, and trust zones.
- Runtime/deployment units, environments, networks, containers, and infrastructure.
- Important business or technical flows and failure/exception paths.

Create a normalized `architecture.json` using `schemas/architecture.schema.json` and the example in `examples/architecture.example.json` as a guide. Every component and connection must have a stable ID. Use `evidence_status` values `confirmed`, `inferred`, or `unknown`. Add `evidence` and `notes` wherever useful. Unknown details belong in `open_questions`, not invented connections.

### 3. Plan diagram views

Generate only views supported by the source:

- `context`: users/actors, system boundary, external systems.
- `container`: applications/services, data stores, external dependencies.
- `component`: internal components of a selected application/service.
- `data_flow`: data movement and integration paths.
- `deployment`: runtime nodes/environments and deployed components.
- `sequence`: ordered interactions for a named scenario.

If a view cannot be grounded in the write-up, omit it and explain why. For a complex system, create multiple focused slides/pages rather than overloading a single view.

### 4. Validate the model

Run:

```bash
python scripts/validate_model.py architecture.json
```

Resolve errors before rendering. Warnings for inferred/unknown relationships may remain if clearly labelled. Check IDs are unique, endpoints exist, labels are meaningful, and each diagram references valid elements.

### 5. Generate deliverables

Run:

```bash
python scripts/generate.py architecture.json --out-dir output
```

Expected outputs:

- `output/architecture.pptx` — primary deliverable; editable native PowerPoint shapes, text, groups/containers, and connectors. Do not flatten the diagram into a screenshot.
- `output/architecture.drawio` — editable diagrams.net XML.
- `output/architecture.docx` — editable Word document containing an executive summary, scope, components, integrations, data stores, flows, assumptions, open questions, and diagram views. Embedded diagrams may be image previews; the document text and tables remain editable.
- `output/architecture.json` — normalized shared model copied alongside the deliverables.
- `output/architecture.svg` — scalable vector overview where supported.

The generator supports a default overview view. Extend `diagrams` in the model to provide multiple views. When a model contains multiple diagrams, create one PowerPoint slide per diagram and one Draw.io page per diagram.

### 6. Quality review

Before returning results:

- Open or render the PPTX and inspect every slide for clipping, overlaps, tiny text, and unreadable connectors.
- Confirm PowerPoint elements are individual shapes/connectors, not a single raster image.
- Open the `.drawio` file in diagrams.net if available; otherwise validate XML structure and state that visual verification was not performed.
- Check Word headings, tables, page breaks, and embedded diagrams.
- Verify all output formats use the same model labels and relationships.
- List any assumptions and open questions prominently.

## Interaction behavior

- If no input write-up is supplied, ask the user to attach or paste it. Do not generate a fictitious architecture.
- If the user supplies a write-up but no output directory, use `docs/architecture/` in the repository when appropriate; otherwise use `architecture-output/`.
- Ask before overwriting existing deliverables.
- If a requested renderer/dependency is missing, explain the dependency and still generate formats that can be produced safely.
- Do not claim a diagram is fully editable in Word. The PowerPoint and Draw.io diagrams are the fully editable diagram artifacts; Word provides editable documentation and an embedded diagram preview.

## Suggested invocation

`/architecture-visualizer Convert the attached architecture write-up into an enterprise architecture model and generate editable PowerPoint, Draw.io, and Word outputs. Ask about ambiguities; do not invent missing details.`
