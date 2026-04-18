# OMORI MCP Toolkit

A lightweight MCP server for driving and testing OMORI through the in-game `omori_mcp` bridge.

## What this repo contains

- `omori_mcp_server.py` - stdio MCP server (FastMCP) that proxies bridge calls to `http://127.0.0.1:43111`.
- `scripts/test_bridge.py` - quick bridge connectivity smoke test.
- `scripts/test_play.py` - quick action/state sanity script.

## Requirements

- Python 3.10+
- `requests`
- `mcp` (FastMCP provider)
- OMORI running with the `omori_mcp` OneLoader bridge active

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the MCP server

```bash
python3 omori_mcp_server.py
```

Optional environment variables:

- `OMORI_BRIDGE_URL` (default: `http://127.0.0.1:43111`)
- `OMORI_VM_BRIDGE_CMD` (default: `muvm -i curl -s`)

## Register in Codex

```bash
codex mcp add omoriE2E --command python3 --args "/absolute/path/to/omori-mcp-toolkit/omori_mcp_server.py"
```

Example with custom bridge URL:

```bash
codex mcp add omoriE2E --command python3 --args "/absolute/path/to/omori-mcp-toolkit/omori_mcp_server.py" --env OMORI_BRIDGE_URL=http://127.0.0.1:43111
```

## Smoke tests

```bash
python3 scripts/test_bridge.py
python3 scripts/test_play.py
```
