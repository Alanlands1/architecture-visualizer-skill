---
name: architecture-visualizer
description: Turn a plain-English description of a system ("users open a web app, it calls an API, the API saves orders in a database") into a clean architecture diagram and editable PowerPoint, Draw.io, Word, SVG, and JSON deliverables. Also draws security and network architecture with zones, firewalls, and encrypted or blocked links, and accepts written architecture documents (PDF, DOCX, PPTX, Markdown, text). Use when a user describes, pastes, or attaches how a system works and wants it drawn, documented, or updated.
metadata:
  slash-command: enabled
---

# Architecture Visualizer

The user describes a system in simple, everyday English. You turn that description into an architecture diagram.

The user is not expected to know architecture vocabulary, diagram types, or this skill's JSON model. They say what the system does; you do the modeling. Every output comes from one shared `architecture.json` model, so the PowerPoint, Draw.io, Word, and SVG files always agree with each other.

## What the user gives you

Either of these is a complete, valid input:

1. **A plain-English description**, typed or pasted into the chat. It may be a single sentence or several paragraphs, and it may be informal, out of order, or incomplete. This is the main way the skill is used.
2. **A written document**: PDF, DOCX, PPTX, Markdown, or TXT. Extract its text with `python scripts/extract_text.py <file> --out extracted.txt`, then treat the text exactly like a typed description. If a scanned PDF extracts as empty, ask for a text version; an empty extraction is not an empty architecture.

If the user invokes the skill with nothing to describe, ask one question: "Describe your system in a few sentences: who uses it, what the main parts are, and what talks to what." Never draw a made-up architecture.

## Security and network descriptions

When the description is about security or networking (firewalls, network areas such as a DMZ, who may reach what, sign-in, secrets, admin access, logging), read `SECURITY-ARCHITECTURE.md` before Step 1. It adds zones, security part types, and encrypted and blocked links, along with the rules for what must never be invented. Everything in this file still applies.

## The workflow

Follow these steps in order. The steps after this section explain each one.

1. Read the description and pull out the parts, the links, and the direction of each link.
2. Decide whether you can draw now or must ask first.
3. Build `architecture.json`.
4. Validate it.
5. Generate the files.
6. Check the result, then tell the user what you drew and what you were unsure about.
7. Apply follow-up changes to the same model.

## Step 1: Read the description

Read the whole description before modeling anything. People often mention a part late ("oh, and it emails the customer") that changes earlier links.

Find three things:

- **Parts**: every person, screen, program, storage place, or outside company the user names. Each becomes a component.
- **Links**: every place where one part uses, calls, sends to, reads from, or waits for another part. Each becomes a connection.
- **Direction**: who starts the interaction. The arrow goes from the part that starts it to the part that receives it.

Use this table to translate everyday wording into the model. The `type` values in the table are the ones the generator colors; any other type still renders, in a neutral color.

| The user says something like | Model it as | `type` |
| --- | --- | --- |
| "users", "customers", "admins", "the support team" | A person or group who uses the system | `actor` |
| "website", "web app", "mobile app", "dashboard", "portal", "screen" | Something people look at and click | `user_interface` |
| "backend", "API", "server", "the app", "gateway" | A program that receives requests | `application` |
| "service", "worker", "job", "function", "processor", "engine" | A program that does one piece of work | `service` |
| "database", "DB", "table", "storage", "saves", "keeps a record of", "cache", "files", "bucket" | A place where data is kept | `database` |
| "queue", "topic", "event bus", "stream", "sends a message", "publishes" | A place where messages wait | `queue` |
| "Stripe", "the bank", "a third party", "another team's system", "email provider" | Something the user's team does not own | `external` |

Translate the linking words the same way:

| The user says | Connection `kind` | Arrow direction |
| --- | --- | --- |
| "calls", "asks", "requests", "talks to", "uses", "logs in through" | `synchronous` | Caller → the part being called |
| "sends to", "publishes", "notifies", "triggers", "drops a message" | `asynchronous` | Sender → receiver |
| "listens to", "picks up from", "consumes", "subscribes to" | `asynchronous` | Queue or source → the part that listens |
| "saves in", "writes to", "stores in", "updates" | `data` | Writer → storage |
| "reads from", "looks up in", "fetches from", "loads from" | `data` | Reader → storage |
| "every night", "once a day", "on a schedule", "in bulk" | `batch` | The job → the part it works on |
| "uploads", "exports a file to", "drops a file in" | `file_transfer` | Sender → destination |

When a part both reads and writes the same storage, draw one connection labeled "Read / write" rather than two arrows.

## Step 2: Draw now, or ask first

Default to drawing. A first diagram the user can correct is worth more than a list of questions, and most gaps can be shown honestly in the diagram itself.

**Ask before drawing only when the diagram would be wrong or empty without the answer:**

- Fewer than two parts can be identified.
- You cannot tell which of two parts starts an interaction, and it changes the picture.
- Two names might be the same thing or two different things (for example "the backend" and "the API").
- Two statements contradict each other.

When you ask, ask at most three questions in one message, in the user's own words, each answerable in a few words. Good: "Does the mobile app talk to the same API as the website, or a different one?" Bad: "Please specify the integration topology."

**For everything else, draw and mark it:**

| Situation | What to do |
| --- | --- |
| The user said it directly | `evidence_status: "confirmed"`. Put their words in `evidence`. |
| The user did not say it, but the description cannot work without it. Example: "the app saves orders" with no storage named. | Add the part or link with `evidence_status: "inferred"`, explain why in `notes`, and add a line to `assumptions`. The diagram shows it with an amber border and an `[INFERRED]` tag. |
| A detail would be nice to know but nothing depends on it: the protocol, the cloud provider, the database brand, who hosts it. | Do not add it. Add a line to `open_questions`. |

Hold these three lines:

- Never name a product, vendor, protocol, or cloud service the user did not name. "A database" stays "Order Database", not "PostgreSQL".
- Never add parts because they are common in systems like this one. No load balancer, login provider, cache, or monitoring unless the user mentioned it or the description cannot work without it.
- Never label an inferred item as confirmed. If you are unsure which one it is, it is inferred.

## Step 3: Build `architecture.json`

Follow `schemas/architecture.schema.json`. `examples/architecture.example.json` shows a small model, `examples/online-bookstore/` shows a detailed description with its model and every generated file, and `references/modeling-guidelines.md` has more detail on evidence and types.

**Top-level fields**

- `title`: the system's name. If the user gave none, make a plain one from what it does ("Order Processing System") and record that in `assumptions`.
- `subtitle`: one line saying what this is, such as "Drawn from a description provided on 2026-11-24".
- `summary`: two or three plain sentences describing the system, written for a reader who has never seen it.
- `scope`: the main things the diagram covers.
- `source_documents`: file names, or `["Description provided in chat"]`.
- `assumptions`, `open_questions`: from Step 2. Write each as a full sentence a non-technical reader can follow.

**Components**

- `id`: short, lowercase, stable, using only letters, digits, `_`, `-`, or `.` (`web`, `orders_api`, `orders_db`). Never change an ID once it exists; follow-up edits depend on it.
- `name`: what the user called it, with their capitalization. Up to about 22 characters fits on one line; longer names wrap to two lines, and anything over 40 is cut short.
- `type`: one value from the Step 1 table.
- `description`: one plain sentence saying what the part does, in at most 90 characters. It wraps inside the box; longer text is cut short.
- `evidence_status`: always set it. A missing value is treated as `unknown` and drawn in red.
- `evidence`: the user's own words, quoted briefly.

**Connections**

- `id`: `e1`, `e2`, `e3`, in the order the story happens. Arrows are numbered in the order of each diagram's `connection_ids`, so list those in story order too.
- `from`, `to`: component IDs, following the direction rules in Step 1.
- `label`: what moves or happens, in two to five words: "Places order", "Read / write", "Payment request". It is printed on the arrow with its step number. Add a protocol such as "HTTPS" only if the user said it.
- `kind`: from the Step 1 table. It decides the arrow style: `asynchronous`, `event`, `batch`, and `file_transfer` are drawn dashed, everything else solid.
- `evidence_status`, `evidence`: as above.

**Diagrams: what each view shows**

The generator lays each diagram out by itself. It puts whatever starts the story on the left and follows the arrows to the right, stacks parts that sit at the same step, and routes arrows around boxes. You choose what goes into each view; you do not position anything.

- Keep each view to eight components or fewer. The validator warns above that.
- Give each view one story: "who uses it", "checkout", "what happens after payment". A part may appear in several views.
- When two parts both link to the same two targets, one crossing is unavoidable. If a view looks tangled, split it.
- Two-way links are fine: draw one connection per direction, each with its own label.

For a small system, one diagram is enough. For a larger one, add more entries to `diagrams`, each selecting a subset of `component_ids` and `connection_ids`:

| Add this view | When | `type` |
| --- | --- | --- |
| The big picture: people, the system's main parts, outside systems | Always, as the first diagram | `context` or `container` |
| One view per area ("checkout", "reporting") | More than eight components in total | `container` |
| The path of one piece of data from start to finish | The user describes a data journey | `data_flow` |
| One named scenario, with connections in story order | The user walks through steps ("first… then… finally…") | `sequence` |

Every connection listed in a diagram needs both of its endpoints in that diagram's `component_ids`. A connection whose other end is outside the view is not drawn, and the validator warns about it.

Shapes come from `type`: a `database` is drawn as a cylinder, an `actor` as a rounded pill, everything else as a box.

The `boundary` field puts a component in a zone, which is drawn as a dashed frame around its parts. Set it only when the user describes network areas or trust zones, and follow `SECURITY-ARCHITECTURE.md` when you do. For ordinary systems, leave `boundary` out.

## Step 4: Validate

```bash
python scripts/validate_model.py architecture.json
```

Fix every `ERROR` before generating. `WARNING` lines about inferred or unknown items are expected when you followed Step 2; leave them.

## Step 5: Generate

```bash
python -m pip install -r requirements.txt   # first run only
python scripts/generate.py architecture.json --out-dir <output folder>
```

Use `docs/architecture/` as the output folder inside a repository, otherwise `architecture-output/`. If the folder already holds deliverables, ask before overwriting them, unless the user is iterating on the diagram you just made in this session.

| File | What it is |
| --- | --- |
| `architecture.pptx` | The main deliverable. A title slide, one slide per diagram, and a closing slide listing assumptions and open questions. Every box, arrow, and label is a real PowerPoint shape the user can move and edit. |
| `architecture.drawio` | The same diagrams for diagrams.net, one page per diagram. Arrows stay attached to their boxes when moved. |
| `architecture.docx` | A written document: summary, every diagram as a picture with its numbered steps listed underneath, a table of parts, a table of links, assumptions, and open questions. |
| `diagrams/NN-<id>.png` and `.svg` | One picture per diagram, for viewing, chat, or a wiki. |
| `architecture.svg` | A copy of the first diagram. |
| `architecture.json` | The model itself. Keep it; follow-up changes start from it. |

If a Python dependency is missing and cannot be installed, say which one and which files could not be produced. Do not report a file as generated unless it exists.

## Step 6: Check, then report

Before replying, check the result:

- Every part the user named appears in the diagram, with the name they used.
- Every arrow points the way the user described.
- No name or description ends in "…". That means it was cut short; shorten the text in the model and regenerate.
- Arrows and their labels are readable. If a view is tangled or labels pile up, split it into two views and regenerate.
- Inferred items carry the `[INFERRED]` tag.
- Look at every picture in `diagrams/`. They show the same layout as the PowerPoint slides. If you could not look at the output, say so; do not claim a visual check you did not do.

Then reply in plain English, in this shape:

1. **What I drew**: one or two sentences retelling the system in the user's words, so they can spot a misunderstanding immediately.
2. **Files**: where the outputs are, with the PowerPoint first.
3. **What I assumed**: each inferred item, one line each. Skip this if there are none.
4. **What I could not tell**: the open questions, phrased so the user can answer in a few words.
5. **What to change**: one line inviting corrections, with an example ("Tell me things like 'the app also sends an email' or 'remove the cache' and I will update it").

Keep the reply short. Do not explain the JSON model, the evidence system, or diagram theory unless the user asks.

## Step 7: Follow-up changes

The user will correct the diagram in the same everyday language. Edit the existing `architecture.json`; never start over.

| The user says | What to change |
| --- | --- |
| "Add a cache between the API and the database" | Add the component and its connections. Place it between its neighbors in `component_ids`. |
| "Remove the queue" | Remove the component, every connection touching it, and its IDs from every diagram. |
| "It's called Billing Service, not Payments" | Change `name` only. Keep the `id`. |
| "The API doesn't talk to the database directly" | Remove that connection. Ask what it goes through if the user did not say. |
| "Yes, it does use a database" / "That's right" | Change the item from `inferred` to `confirmed` and remove the matching assumption. |
| "It's Postgres" / "It runs on AWS" | Update the name or description, and remove the answered open question. |
| "This is too crowded" | Split into more views as described in Step 3. |
| "Move this box over there" | The layout is automatic. Tell the user they can drag shapes in the PowerPoint or Draw.io file, or offer to split the view. |
| "Show me just the checkout part" | Add a diagram containing only those components and connections. |

After each change: validate, regenerate into the same folder, and reply with only what changed.

## Worked example

**The user writes:**

> Customers use our mobile app to order food. The app talks to our backend. The backend saves the order and then asks Stripe to take the payment. When the payment goes through, the kitchen gets notified on their tablet.

**How to read it:**

- Parts: Customers (`actor`), mobile app (`user_interface`), backend (`application`), Stripe (`external`), the kitchen's tablet (`user_interface`).
- "saves the order" needs storage that was never named, so add an Order Database as `inferred`.
- "the kitchen gets notified" does not say how. The link is real, so draw it backend → kitchen tablet, labeled "Order notification", `kind: asynchronous`, `confirmed`. The mechanism is unknown, so it goes to `open_questions`. Do not invent a queue or a push service.
- Nothing blocks drawing, so draw without asking.

**The model:**

```json
{
  "title": "Food Ordering System",
  "subtitle": "Drawn from a description provided in chat",
  "summary": "Customers order food from a mobile app. A backend records each order, takes payment through Stripe, and notifies the kitchen once payment succeeds.",
  "scope": ["Ordering", "Payment", "Kitchen notification"],
  "source_documents": ["Description provided in chat"],
  "components": [
    {"id": "customer", "name": "Customers", "type": "actor", "description": "People ordering food", "evidence_status": "confirmed", "evidence": "Customers use our mobile app to order food."},
    {"id": "app", "name": "Mobile App", "type": "user_interface", "description": "Where customers place orders", "evidence_status": "confirmed", "evidence": "Customers use our mobile app to order food."},
    {"id": "backend", "name": "Backend", "type": "application", "description": "Handles orders and payment", "evidence_status": "confirmed", "evidence": "The app talks to our backend."},
    {"id": "orders_db", "name": "Order Database", "type": "database", "description": "Keeps the saved orders", "evidence_status": "inferred", "notes": "The backend saves the order, so it needs somewhere to keep it. The user did not name the storage."},
    {"id": "stripe", "name": "Stripe", "type": "external", "description": "Takes the payment", "evidence_status": "confirmed", "evidence": "asks Stripe to take the payment"},
    {"id": "kitchen", "name": "Kitchen Tablet", "type": "user_interface", "description": "Shows new orders to the kitchen", "evidence_status": "confirmed", "evidence": "the kitchen gets notified on their tablet"}
  ],
  "connections": [
    {"id": "e1", "from": "customer", "to": "app", "label": "Orders food", "kind": "synchronous", "evidence_status": "confirmed", "evidence": "Customers use our mobile app to order food."},
    {"id": "e2", "from": "app", "to": "backend", "label": "Places order", "kind": "synchronous", "evidence_status": "confirmed", "evidence": "The app talks to our backend."},
    {"id": "e3", "from": "backend", "to": "orders_db", "label": "Saves order", "kind": "data", "evidence_status": "inferred", "notes": "Follows from the inferred Order Database."},
    {"id": "e4", "from": "backend", "to": "stripe", "label": "Payment request", "kind": "synchronous", "evidence_status": "confirmed", "evidence": "asks Stripe to take the payment"},
    {"id": "e5", "from": "backend", "to": "kitchen", "label": "Order notification", "kind": "asynchronous", "evidence_status": "confirmed", "evidence": "When the payment goes through, the kitchen gets notified on their tablet."}
  ],
  "diagrams": [
    {"id": "overview", "title": "Food Ordering System: How an Order Flows", "type": "container", "component_ids": ["customer", "app", "backend", "orders_db", "stripe", "kitchen"], "connection_ids": ["e1", "e2", "e3", "e4", "e5"]}
  ],
  "assumptions": ["Orders are kept in a database. The description says the backend saves the order but does not say where."],
  "open_questions": ["How does the kitchen tablet get notified: does the backend push to it, or does the tablet check for new orders?", "Does Stripe report the payment result back to the backend right away, or later?"]
}
```

**The reply:**

> **What I drew:** Customers order in the mobile app, which sends the order to your backend. The backend saves it, asks Stripe to take the payment, and then notifies the kitchen tablet.
>
> **Files:** `architecture-output/architecture.pptx` (editable slides), plus `.drawio`, `.docx`, and `.json` in the same folder, and a picture of each diagram in `architecture-output/diagrams/`.
>
> **What I assumed:** The backend keeps orders in a database. You said it saves the order but not where, so that box is marked as inferred.
>
> **What I could not tell:** How does the kitchen tablet get notified: does the backend push to it, or does the tablet check for new orders?
>
> Tell me what to change, for example "the app also shows order status" or "it's not a database, it's a spreadsheet".

## Rules that always apply

1. The user's description is the source of truth. What they said is confirmed, what you had to add is inferred and marked, and everything else is an open question.
2. Use the user's words for names. Do not rename their parts into formal architecture terms.
3. Write every label, description, assumption, and question in plain English that a non-technical reader can follow.
4. Never put passwords, keys, tokens, or personal data into the model, even if the user's description contains them. Leave them out and say that you did.
5. All files come from one `architecture.json`. Never edit one output by hand to differ from the others.
6. The diagrams in Word are pictures. Point users to the PowerPoint or Draw.io file when they want to move or restyle individual shapes.
7. Use no vendor logos or product icons. The visual style is described in `references/enterprise-design-system.md`.

## Suggested invocation

```text
/architecture-visualizer Customers use our mobile app to order food. The app talks to our backend. The backend saves the order and asks Stripe to take the payment. Then the kitchen gets notified on their tablet.
```
