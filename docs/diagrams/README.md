# Architecture diagrams

Mermaid diagrams drawn from the code as it is, not from older documents. Jira KAN-55.

- Commit: `e5c23fd` (branch `r3/a_docs`)
- Date: 15 Nov 2026

| File | What it shows |
| --- | --- |
| [01_system_context.md](01_system_context.md) | The gateway, pipeline, Prime, dashboard, CLI, extension, Velaris and the outside systems the code calls, with protocol and auth on each edge |
| [02_call_flow.md](02_call_flow.md) | One request from the dashboard: start a factory run, middleware order, policy, background execution, model calls, events; and a Velaris proxied call with the signed identity |
| [03_approval_flow.md](03_approval_flow.md) | Real approval states (Prime, Velaris proposals, spec review, decision gates), who can move them, where the second person rule is and is not enforced |
| [04_data_flow.md](04_data_flow.md) | Where each kind of data lives, the org boundary, ledger chains and anchors, Redis keys, what leaves for third parties |
| [05_deployment.md](05_deployment.md) | Compose with host nginx, Helm and AWS Terraform, ports, volumes, secrets, non root, and where they differ. Not verified by a real run |

## How to render

- GitHub shows each Mermaid block in the file view.
- In VS Code, use a Mermaid preview extension.
- On the command line, if installed: `mmdc -i 01_system_context.md -o 01.svg` (Mermaid CLI). It was not available when these were written, so the blocks were checked by reading only.

## Rules used

- An edge or a state appears only if a call site or code path was found. Each file ends with the source files and line numbers, and a list of what is not shown or not verified.
- Line numbers are for the commit above. They move when the files change.
