# Architecture modeling guidelines

## Evidence status
- `confirmed`: explicitly stated in the write-up or directly shown by an authoritative supplied artifact.
- `inferred`: plausible interpretation, not explicit; explain why in `notes` and visually label it.
- `unknown`: relevant but not established. Prefer an open question over adding a speculative connection.

## Component types
Prefer the seven types the generator colors: `actor`, `user_interface`, `application`, `service`, `database`, `queue`, and `external`. Other concise snake_case values such as `gateway`, `identity_provider`, `batch_job`, `file_store`, and `infrastructure` are valid and render in a neutral color.

## Connection kinds
Use values such as `synchronous`, `asynchronous`, `event`, `data`, `batch`, `file_transfer`, and `network`. Preserve actual protocol/technology in the connection `label` only when supported by evidence.

## Multiple diagrams
A diagram object selects component and connection IDs. Each connection's endpoints must appear in that diagram. If a connection crosses view boundaries, either include both endpoints or omit it from that view. Keep stable IDs when revising a model so diffs remain useful.
