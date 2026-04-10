# MCP Server Configuration Guide for Routine Authors

When a task needs access to external tools (browser control, database, APIs), configure MCP servers at the **step level** in the routine YAML. All tasks in that step inherit the servers.

## Schema

```yaml
steps:
  - id: "S-01"
    title: "Browser testing"
    mcp_servers:
      - name: "browser"            # required: unique name
        command: "npx"              # stdio transport (OR url, not both)
        args: ["-y", "@playwright/mcp@latest", "--headless"]
        env:                        # optional env vars for the process
          DISPLAY: ":99"
        timeout_seconds: 60         # default: 30
    tasks: [...]
```

## Transport: `command` (stdio) vs `url` (SSE/HTTP)

Exactly one of `command` or `url` must be set per server.

**stdio** — runs a local process, communicates via stdin/stdout:
```yaml
mcp_servers:
  - name: "browser"
    command: "npx"
    args: ["-y", "@playwright/mcp@latest", "--headless"]
```

**url** — connects to a remote SSE/HTTP endpoint:
```yaml
mcp_servers:
  - name: "browser"
    url: "https://my-playwright-server.example.com/sse"
    auth_token_env: "BROWSER_MCP_TOKEN"   # env var name, never the token itself
```

## Agent compatibility

| Agent type      | stdio | url (http) | url (https) |
|-----------------|-------|------------|-------------|
| CLI (Claude)    | yes   | yes        | yes         |
| OpenHands       | yes   | yes        | yes         |
| Codex           | yes   | yes        | yes         |
| Claude SDK      | no    | no         | **https only** |

Claude SDK uses Anthropic's MCP Connector beta which requires `https://` URLs. If your routine may run on Claude SDK agents, either:
- Use `url:` with an HTTPS endpoint, or
- Provide both transports and let the executor pick the compatible one (not yet supported — use separate steps if needed)

## Common MCP servers

### Browser control (Playwright)
```yaml
mcp_servers:
  - name: "browser"
    command: "npx"
    args: ["-y", "@playwright/mcp@latest", "--headless"]
```
Tools provided: `browser_navigate`, `browser_click`, `browser_fill`, `browser_screenshot`, `browser_evaluate`, etc.

### Browser control (Browserbase — cloud hosted)
```yaml
mcp_servers:
  - name: "browser"
    command: "npx"
    args: ["-y", "@anthropic/mcp-server-browserbase"]
    env:
      BROWSERBASE_API_KEY: "{{browserbase_api_key}}"
      BROWSERBASE_PROJECT_ID: "{{browserbase_project_id}}"
```

## Auth tokens

Never put tokens directly in YAML. Use `auth_token_env` to reference an environment variable by name:

```yaml
mcp_servers:
  - name: "my-api"
    url: "https://api.example.com/mcp/sse"
    auth_token_env: "MY_API_TOKEN"    # executor reads os.environ["MY_API_TOKEN"]
```

## When to use MCP servers

- Task needs browser interaction (testing UI, scraping, form filling)
- Task needs access to an external API that has an MCP server
- Task needs a tool not built into the agent (database queries, file conversion)

## When NOT to use MCP servers

- Task only needs filesystem and terminal access (agents already have these)
- Task only needs git operations (agents already have git)
- The tool is available as a CLI command (just reference it in `task_context` or `auto_verify`)
