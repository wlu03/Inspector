# Inspector

An MCP server that lets a coding agent see, operate, and test the app it just built,
across web, Electron, Android, and iOS, and feed back reproducible, source-linked findings.

## Start here

- **Install and quickstart:** the [project README](https://github.com/wlu03/Inspector#readme).
- **MCP tools:** the [Tool Reference](tool-reference.md) is generated from the server, so it never drifts.
- **How the loop works:** [MCP Contract](03-mcp-contract.md) and [Core Loop](04-core-loop.md).
- **How it is built:** [Architecture](02-architecture.md).

## Build this site locally

```bash
pip install mkdocs-material
mkdocs serve
```

The tool reference is regenerated with `python scripts/gen_docs.py` (a test keeps it in sync).
