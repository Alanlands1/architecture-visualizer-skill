# Architecture modeling guidelines

## Evidence status
- `confirmed`: explicitly stated in the write-up or directly shown by an authoritative supplied artifact.
- `inferred`: plausible interpretation, not explicit; explain why in `notes` and visually label it.
- `unknown`: relevant but not established. Prefer an open question over adding a speculative connection.

## Component types
Prefer the seven types the generator colors: `actor`, `user_interface`, `application`, `service`, `database`, `queue`, and `external`. Security descriptions add `firewall`, `waf`, `vpn`, `load_balancer`, `gateway`, `identity_provider`, `secrets_store`, and `monitoring`; see `SECURITY-ARCHITECTURE.md`. Any other concise snake_case value is valid and renders in a neutral color.

## Connection kinds
Use values such as `synchronous`, `asynchronous`, `event`, `data`, `batch`, `file_transfer`, and `network`. Preserve actual protocol/technology in the connection `label` only when supported by evidence.

## Zones and security links
A top-level `zones` list names the network or trust areas, least trusted first. A component joins a zone through `boundary`. Connections may carry `protocol`, `port`, `encrypted`, and `blocked`. Set all of these only from what the source states; `SECURITY-ARCHITECTURE.md` has the rules.

## Multiple diagrams
A diagram object selects component and connection IDs. Each connection's endpoints must appear in that diagram. If a connection crosses view boundaries, either include both endpoints or omit it from that view. Keep stable IDs when revising a model so diffs remain useful.
