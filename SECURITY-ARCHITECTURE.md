# Security and network architecture

Read this file when the user's description is about security or networking: firewalls, network areas, who may reach what, sign-in, secrets, admin access, logging, or monitoring. It adds to `SKILL.md`; it does not replace it. The seven-step workflow, the evidence rules, and the reply format in `SKILL.md` all still apply.

The user still writes plain English, such as "the internet can only reach the DMZ, and only the app zone may talk to the database". You turn that into zones, security parts, and links marked as encrypted or blocked.

`examples/secure-patient-portal/` shows a complete run: the description, the model, and every generated file.

## What is different for security diagrams

A normal architecture diagram answers "what talks to what". A security diagram also has to answer three more questions:

1. **Where does each part live?** Parts are grouped into zones, and the zone a part is in says how exposed it is.
2. **What protects each crossing?** Firewalls, gateways, and sign-in checks sit between zones.
3. **What is allowed, what is protected, and what is forbidden?** Links carry a protocol and port, and are marked encrypted or blocked.

The generator draws all three, but only from what the user actually said.

## Zones

A zone is a named area of the network or of trust. In the diagram it is a dashed frame with its name in the top corner, and the parts inside it are kept together.

**Add zones when the user describes areas**, in words like these:

| The user says something like | Zone |
| --- | --- |
| "the internet", "outside", "public", "anyone" | Internet |
| "DMZ", "edge", "perimeter", "public subnet" | DMZ |
| "internal network", "private subnet", "app tier", "behind the firewall" | Their name for it, such as "App zone" |
| "data tier", "database subnet", "the most protected area", "restricted" | Their name for it, such as "Data zone" |
| "management network", "admin network", "ops" | Management zone |
| "our AWS account", "the VPC", "on-prem", "the office", "the data center" | One zone per place they name |
| "a partner's network", "the vendor's cloud" | One zone per outside party |

**How to model them:**

- Add a top-level `zones` list. Each entry has an `id`, the `name` the user used, and a one-sentence `description` in their words.
- List the zones from least trusted to most trusted, the way traffic comes in: Internet, then DMZ, then the internal zones. The diagram draws them left to right in that order, in every view.
- Set each component's `boundary` to the `id` of its zone.
- A part the user did not place in any zone gets no `boundary`. It is drawn outside the frames. Do not guess a zone for it; add an open question if the zone matters.
- A cloud service outside the user's network, such as a sign-in provider, belongs in the Internet zone or in a zone of its own, whichever the user's words support.

### Zones inside zones

Users often describe an area inside a bigger one: "in Azure we have a security VNet and an application VNet", "the data subnet inside the VPC". Model the big area as a zone of its own and give each inner zone a `parent`:

```json
"zones": [
  {"id": "onprem", "name": "On-Premise"},
  {"id": "azure", "name": "Azure"},
  {"id": "secvnet", "name": "Security VNet", "parent": "azure"},
  {"id": "appvnet", "name": "Application VNet", "parent": "azure"}
]
```

- The outer zone is drawn as a frame around its inner zones. Inner zones of the same parent always sit side by side.
- Set each component's `boundary` to the innermost zone the user placed it in. A part the user only placed in "Azure" gets `boundary: "azure"` and sits inside the outer frame, outside the inner ones.
- Nest only when the user said one area is inside another. Two levels read well; three is the limit.
- A part that connects two zones without belonging to either, such as a private link between on-premise and the cloud, gets no `boundary` and is drawn between the frames.

Do not use zones for ordinary grouping such as "frontend" and "backend" when the user is not describing network areas or trust. Leave `boundary` out in that case. A view can also turn frames off with `"show_zones": false`.

## Security parts

Use these `type` values in addition to the ones in `SKILL.md`. Each has its own shape or colour, and the type name is printed in the box so the meaning never depends on colour alone.

| The user says something like | `type` | Drawn as |
| --- | --- | --- |
| "firewall", "security group", "network ACL", "packet filter" | `firewall` | Hexagon |
| "WAF", "web application firewall", "bot protection" | `waf` | Hexagon |
| "VPN", "VPN gateway", "remote access", "site-to-site tunnel" | `vpn` | Hexagon |
| "load balancer", "reverse proxy", "ingress" | `load_balancer` | Box |
| "API gateway", "proxy", "gateway" | `gateway` | Box |
| "login provider", "SSO", "Okta", "Entra ID", "Active Directory", "identity provider" | `identity_provider` | Green box |
| "vault", "key vault", "secrets manager", "KMS", "HSM", "certificate store" | `secrets_store` | Green cylinder |
| "SIEM", "log collector", "monitoring", "intrusion detection", "audit log" | `monitoring` | Grey-blue box |
| "bastion", "jump box", "jump host" | `service` | Box |

Name a product only when the user named it. "Our SIEM, which is Splunk" becomes "Splunk SIEM". "Our SIEM" stays "SIEM".

## Links: allowed, encrypted, blocked

Every link still needs `from`, `to`, `label`, and `kind` as in `SKILL.md`. Security links can carry four more fields. Set each one only when the user said it.

| Field | Set it when the user says | What the diagram shows |
| --- | --- | --- |
| `protocol` | "over HTTPS", "using OIDC", "with SSH", "TLS" | The protocol under the label |
| `port` | "on port 443", "port 5432" | The port next to the protocol |
| `encrypted: true` | "encrypted", "over TLS", "HTTPS", "SSH", "through the VPN tunnel" | A teal arrow and the word "encrypted" |
| `blocked: true` | "is not allowed to", "must never", "is blocked", "is denied", "cannot reach" | A red arrow and the word "BLOCKED" |

Translate security verbs like this:

| The user says | Model it as |
| --- | --- |
| "goes through", "passes", "sits in front of", "sits behind" | A chain: source → the control → destination, one link per hop |
| "allows only X", "only lets X through" | A normal link labelled with X. Put the rule in the control's `description`. |
| "blocks", "denies", "drops", "must never reach" | A link from the source to the forbidden destination with `blocked: true` |
| "checks the login with", "authenticates against", "verifies with" | A link from the part that asks → the identity provider |
| "fetches the password from", "gets its keys from" | A link from the part that asks → the secrets store |
| "sends logs to", "is monitored by", "audited by" | A link from the source → the monitoring part, `kind: asynchronous` |
| "alerts", "pages", "notifies" | A link from the monitoring part → the team, `kind: asynchronous` |

Three points about blocked links:

- Draw a blocked link only for a path the user called out as forbidden. Do not draw every path that happens to be absent.
- A blocked link goes between the two parts that may not talk, not through the firewall that stops it. If the user said which control enforces the rule, write that in the link's `notes`.
- When the user states a rule about whole zones ("nothing in the DMZ may reach the data zone"), draw one blocked link between the most relevant parts of those zones and put the full rule in `notes`.

HTTPS, TLS, SSH, and a VPN tunnel are encrypted by definition, so `encrypted: true` is confirmed when the user names one of them. For any other link, do not assume either way.

## Side panels: controls that are not boxes

Security descriptions often list controls that apply to the whole system and have no place in the flow: "all traffic uses TLS 1.2 or higher", "code is scanned with SAST and DAST", "backups are geo-replicated". Do not turn these into boxes with invented arrows. Put them in side panels, which are drawn as titled cards to the right of the diagram.

```json
"panels": [
  {"id": "crypto", "title": "Cryptography", "items": ["TLS 1.2 or higher", "Encryption at rest with customer managed keys"]},
  {"id": "iam", "title": "Identity and Access", "items": ["MFA for all admins", "Access reviews every quarter"]}
]
```

- Group the statements under the headings the user used. If they gave none, use the usual security domains: Identity and Access, Network Security, Cryptography, Data Protection, Logging and Monitoring, Application Security, Business Continuity, Threat and Vulnerability, Governance and Risk.
- Each item is one short statement in the user's words, under 110 characters. Keep to six items or fewer per panel.
- A view shows a panel only when the view's `panel_ids` lists it. Show the panels that match the view's question: the sign-in view gets Identity and Access, the logging view gets Logging and Monitoring. One overview may show them all, up to eight.
- Every item must come from the description. A panel is read as a statement of fact, exactly like a box. Never fill a panel with controls the system ought to have, and leave out a heading the user said nothing about.
- A named tool that takes part in the flow is still a box. A tool that is only mentioned ("scanned by Veracode", "monitored with Wiz") is a panel item.

## What never goes in the model

`SKILL.md` already forbids secrets. For security descriptions this needs more care, because users often paste real details:

- Never include passwords, keys, tokens, certificates, or connection strings. Leave them out and say that you did.
- Leave out IP addresses, hostnames, account IDs, and firewall rule numbers unless the user asks for them to be shown. Ports and protocol names are fine.
- Leave out the names of individual people. Use roles: "Admins", "Security Team".
- Do not record known weaknesses as facts in the diagram. If the description reveals one ("the database port is open to the internet"), draw what the user described and raise it as an open question, not a judgement.

## What you must not invent

Security diagrams are read as statements of fact, and a control that is drawn but does not exist is worse than a gap. Hold these lines:

- Never add a firewall, WAF, VPN, encryption, sign-in check, or logging because a system like this should have one. If the user did not say it, it is not in the diagram.
- Never mark a link encrypted because it ought to be.
- Never place a part in a zone the user did not put it in.
- Never mark a control as `confirmed` on the strength of a product name alone. "We use AWS" does not confirm security groups.

Missing controls become open questions instead. Ask about the gaps a security reviewer would notice first, and keep the list short:

- A link that crosses zones with no control named on it.
- A link into a data store with no word on encryption.
- A way in for people (admins, partners, support) with no sign-in check described.
- Parts that hold sensitive data with no logging described.
- A zone rule the user stated without saying what enforces it.

Phrase each one as a plain question: "Is the link from the VPN Gateway to the Bastion Host encrypted?" Do not phrase it as a finding or a recommendation unless the user asks for a review.

## Planning the views

Zones take horizontal room: every zone gets its own columns, and a chain inside a zone adds more. A view wider than five columns becomes hard to read on a slide.

- Keep each view to five columns or fewer. A chain of six parts in a row needs two views.
- Keep to the eight-component limit from `SKILL.md`.
- Give each view one security question. These five cover most systems:

| View | Shows | `type` |
| --- | --- | --- |
| Zones and the way in | The path from outside to the data, through every control, plus the main blocked path | `context` |
| Sign-in and secrets | Who checks identity, where secrets are kept, who fetches them | `container` |
| Privileged access | How admins and support staff reach servers | `sequence` |
| Logging and alerts | What sends logs where, and who is alerted | `data_flow` |
| Outside parties | Links to partners, vendors, and cloud services | `container` |
| Full security view | The main path, the supporting services, and every side panel | `context` |

Leave out any view the description does not support.

Supporting services that the user listed without saying what they connect to (for example "we also use Azure Monitor and Azure Backup") may be drawn as boxes with no arrows inside their zone. Do not invent arrows for them; ask what they connect to as an open question.

Arrows that cross a zone without stopping there are drawn as lanes passing through that zone's frame. That is expected. If a view has many of them, split it.

## Worked example

**The user writes:**

> Users come in from the internet. Everything goes through our firewall first, which only allows HTTPS. Behind it, in the DMZ, is the web server. The web server talks to the database in the internal network over TLS. The internet must never reach the database directly.

**How to read it:**

- Zones, in the order traffic comes in: Internet, DMZ, Internal network.
- Parts: Users (`actor`, Internet), Firewall (`firewall`), Web Server (`application`, DMZ), Database (`database`, Internal network).
- The firewall's zone was not stated. It stands between the internet and the DMZ, so it gets no `boundary` and an open question, not a guess.
- "only allows HTTPS" gives the first link `protocol: "HTTPS"` and `encrypted: true`, and goes into the firewall's `description`.
- "over TLS" gives the database link `protocol: "TLS"` and `encrypted: true`.
- "must never reach the database directly" is a blocked link from Users to Database.
- Nothing was said about logging, sign-in, or encryption on disk. Those are open questions, not parts.

**The model (shortened):**

```json
{
  "title": "Web Application: Security Architecture",
  "zones": [
    {"id": "internet", "name": "Internet", "description": "Where users come from."},
    {"id": "dmz", "name": "DMZ", "description": "Where the web server sits, behind the firewall."},
    {"id": "internal", "name": "Internal network", "description": "Where the database sits."}
  ],
  "components": [
    {"id": "user", "name": "Users", "type": "actor", "boundary": "internet", "description": "People using the web application", "evidence_status": "confirmed", "evidence": "Users come in from the internet."},
    {"id": "fw", "name": "Firewall", "type": "firewall", "description": "Only allows HTTPS", "evidence_status": "confirmed", "evidence": "our firewall first, which only allows HTTPS"},
    {"id": "web", "name": "Web Server", "type": "application", "boundary": "dmz", "description": "Serves the web application", "evidence_status": "confirmed", "evidence": "in the DMZ, is the web server"},
    {"id": "db", "name": "Database", "type": "database", "boundary": "internal", "description": "Keeps the application's data", "evidence_status": "confirmed", "evidence": "the database in the internal network"}
  ],
  "connections": [
    {"id": "e1", "from": "user", "to": "fw", "label": "Web traffic", "kind": "synchronous", "protocol": "HTTPS", "encrypted": true, "evidence_status": "confirmed", "evidence": "Everything goes through our firewall first, which only allows HTTPS."},
    {"id": "e2", "from": "fw", "to": "web", "label": "Allowed traffic", "kind": "synchronous", "evidence_status": "confirmed", "evidence": "Behind it, in the DMZ, is the web server."},
    {"id": "e3", "from": "web", "to": "db", "label": "Reads and writes data", "kind": "data", "protocol": "TLS", "encrypted": true, "evidence_status": "confirmed", "evidence": "talks to the database in the internal network over TLS"},
    {"id": "e4", "from": "user", "to": "db", "label": "Direct access", "kind": "data", "blocked": true, "evidence_status": "confirmed", "evidence": "The internet must never reach the database directly."}
  ],
  "assumptions": [],
  "open_questions": [
    "Which zone is the firewall in: the DMZ, or between the internet and the DMZ?",
    "Is there a second firewall between the DMZ and the internal network?",
    "How do users sign in?",
    "Is the database encrypted on disk?",
    "Where do the firewall and the web server send their logs?"
  ]
}
```

**The reply** follows the shape in `SKILL.md`: what you drew, the files, what you assumed, what you could not tell, and an invitation to correct it. For a security diagram, put the open questions before the invitation and keep them as questions.
