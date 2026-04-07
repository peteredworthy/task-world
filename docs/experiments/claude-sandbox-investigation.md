# Claude Code macOS Sandbox Investigation

**Date:** 2026-04-07  
**Investigator:** Claude (claude-sonnet-4-6) via interactive session  
**Trigger:** Agent in worktree reported sandbox settings were not restricting filesystem access outside the worktree.

---

## Background

Worktrees in this project have `.claude/settings.json` files that configure the sandbox:

```json
{
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowWrite": ["./", "//tmp"]
    },
    "network": {
      "allowedDomains": ["localhost", "127.0.0.1"]
    }
  }
}
```

The expectation was that the sandbox would block access outside the worktree. The report was that rules appeared to be in a bad order: allows first, denies after, with no base deny-all — which (under first-match semantics) would make the denies pointless.

---

## Investigation Method

### Step 1: Locate the binary

Claude Code is a Bun SEA (Single Executable Application) at:
```
~/.local/share/claude/versions/2.1.92
```

### Step 2: Extract JS source via `strings`

The binary embeds minified JavaScript. Using `strings` with byte-offset targeting (`dd` + `strings`) to locate and read key functions:

```bash
grep -boa "function Zx4" ~/.local/share/claude/versions/2.1.92
dd if=<binary> bs=1 skip=<offset> count=<n> | python3 -c "
import sys; data=sys.stdin.buffer.read()
text = ''.join(chr(b) if 32<=b<127 else ' ' for b in data)
print(text[:N])
"
```

### Step 3: Map the call chain

The sandbox wrapping pipeline on macOS:

```
settings.json
    → d4 (parsed config via Zod schema)
    → Vx4() (getFsReadConfig)  → readConfig {denyOnly, allowWithinDeny}
    → Sx4() (getFsWriteConfig) → writeConfig {allowOnly, denyWithinAllow}
    → Zx4({readConfig, writeConfig, ...}) → SBPL profile string
    → Rx4(readConfig) → read rules array
    → Gx4(writeConfig) → write rules array
    → Btq({command, ..., readConfig, writeConfig}) → sandboxed command
    → sandbox-exec -p <profile> bash -c <command>
```

### Step 4: Empirical SBPL semantics testing

Used `sandbox-exec` directly to test rule evaluation order:

```bash
# Test 1: broad allow BEFORE specific deny
sandbox-exec -p '(version 1)
(deny default)
...(system rules)...
(allow file-read*)
(deny file-read* (subpath "/private/tmp"))' sh -c 'cat /private/tmp/test.txt'

# Test 2: specific deny BEFORE broad allow
sandbox-exec -p '(version 1)
(deny default)
...(system rules)...
(deny file-read* (subpath "/private/tmp"))
(allow file-read*)' sh -c 'cat /private/tmp/test.txt'
```

Both tests: `cat` was denied. Order didn't matter.

```bash
# Test 3: parent allow + subdirectory deny (denyWithinAllow scenario)
# allow BEFORE deny
(allow file-read* (subpath "/"))
(deny file-read* (subpath "/private/tmp/sbpl-test-dir/subdir"))

# deny BEFORE allow
(deny file-read* (subpath "/private/tmp/sbpl-test-dir/subdir"))
(allow file-read* (subpath "/"))
```

Both: parent directory readable, subdirectory denied. Order didn't matter.

```bash
# Test 4: equal-specificity — does order matter?
# allow AFTER deny (same subpath):
(deny file-read* (subpath "/tmp"))
(allow file-read* (subpath "/tmp"))  ← LAST wins
→ file readable

# deny AFTER allow (same subpath):
(allow file-read* (subpath "/tmp"))
(deny file-read* (subpath "/tmp"))   ← LAST wins
→ file denied
```

Order matters only for equal-specificity rules. Last rule wins in that case.

---

## Key Findings

### Finding 1: SBPL uses most-specific-wins semantics

macOS Sandbox Profile Language (SBPL) does **not** use first-match semantics. It uses:

1. **Most-specific rule wins** — a rule with a longer/deeper path qualifier beats one with a shorter or no qualifier
2. **For equal-specificity: last rule wins** — among rules matching the same path equally specifically, the later rule in the profile takes effect
3. **`(deny default)` is a fallback** — it only applies when no explicit rule matches; it does not compete positionally with explicit rules

This means the reported rule ordering concern (allows before denies) is **not** a real bug for most cases. The specific denies win over broad allows due to specificity, regardless of order.

### Finding 2: `(deny default)` is line 2 of every generated profile

From the `Zx4` function:

```javascript
let D = [
  "(version 1)",
  `(deny default (with message "${j}"))`,  // ← LINE 2
  "",
  `; LogTag: ${j}`,
  // ... all the specific allows ...
  `; File read`,
  ...Rx4(readConfig),
  `; File write`,
  ...Gx4(writeConfig),
];
```

The base deny-all IS present. The concern about "no base deny" was incorrect.

### Finding 3: The actual bug — reads are completely unrestricted

`allowWrite` only restricts what the Bash tool can **write**. It has no effect on reads. The `Rx4()` function always starts with:

```javascript
function Rx4(H, _, q) {
  if (!H) return ["(allow file-read*)"];
  let K = [];
  K.push("(allow file-read*)");  // ALWAYS added, even when H is provided
  for (let $ of H.denyOnly || []) { ... }  // empty when denyRead not set
  ...
}
```

With only `allowWrite` configured, `d4.filesystem.denyRead` is an empty array, so the loop produces nothing. The `; File read` section in the generated profile contains only:

```scheme
; File read
(allow file-read*)
```

**An agent in a worktree configured this way can read any file on the filesystem.**

### Finding 4: The schema supports read restriction via `denyRead`

The Zod schema for `sandbox.filesystem` exposes:

```typescript
{
  allowWrite:  string[],  // paths to allow writing; merged with Edit(...) allow rules
  denyWrite:   string[],  // paths to deny writing;  merged with Edit(...) deny rules
  denyRead:    string[],  // paths to deny reading;  merged with Read(...) deny rules
  allowRead:   string[],  // paths to re-allow within denyRead regions
  allowManagedReadPathsOnly: boolean  // managed-only: deny all reads except allowRead
}
```

`denyRead: ["/"]` + `allowRead: [<needed system paths>, "./"]` would produce:

```scheme
; File read
(allow file-read*)                              ; least specific
(deny file-read* (subpath "/"))                 ; more specific — blocks most reads
(allow file-read* (literal "/"))               ; special case: root dir itself
(allow file-read* (subpath "/usr"))            ; system paths
(allow file-read* (subpath "/System"))
(allow file-read* (subpath "/private/tmp/sbpl-test-dir"))  ; worktree
```

With most-specific-wins: the worktree `(allow ...)` beats the `(deny /)`, and the `(deny /)` beats the bare `(allow file-read*)`. This works correctly.

### Finding 5: Verified the fix works empirically

```bash
sandbox-exec -p '(version 1)
(deny default)
...(system allows)...
(allow file-read*)
(deny file-read* (subpath "/"))
(allow file-read* (literal "/"))
(allow file-read* (subpath "/usr")) (allow /bin /System /Library /private/var /private/etc)
(allow file-read* (subpath "/private/tmp/sbpl-test-dir"))
(allow file-write* (subpath "/private/tmp/sbpl-test-dir/output"))' \
  sh -c 'cat /allowed-dir/file > /output; cat /blocked-file > /output'
```

Results:
- Reads from `/private/tmp/sbpl-test-dir/parent-file.txt` → **succeeded**
- Reads from `/private/tmp/sbpl-test.txt` (outside) → **Operation not permitted**
- Reads from `/Users` → **Operation not permitted**

### Finding 6: Linux sandbox (bubblewrap) handles this naturally

The Linux code path (`Jx4`) uses `bwrap --ro-bind / /` as the base mount (read-only root), then `--bind /worktree /worktree` for write-allowed paths. This naturally restricts both reads and writes in one configuration. The macOS SBPL approach requires explicit `denyRead` to achieve the same isolation.

### Finding 7: Network restriction uses a proxy, not SBPL rules

The `allowedDomains` setting doesn't generate SBPL domain rules. When `needsNetworkRestriction` is true, SBPL only exposes localhost ports, and all external traffic is routed through a MITM HTTP/SOCKS proxy bridge that enforces domain allowlisting. If the proxy fails to start, network may be unrestricted.

---

## Corrected Understanding of Profile Structure

For worktree settings with `allowWrite: ["./", "//tmp"]` and no `denyRead`:

```scheme
(version 1)
(deny default (with message "<logTag>"))        ; ← BASE DENY, line 2

; Process permissions
(allow process-exec)
(allow process-fork)
...

; Mach IPC
(allow mach-lookup (global-name "com.apple.logd") ...)

; POSIX IPC, IOKit, sysctl, notifications...

; Network (unrestricted when needsNetworkRestriction=false)
(allow network*)

; File read  ← THE PROBLEM
(allow file-read*)                              ; ← unrestricted reads

; File write  ← works correctly
(allow file-write* (subpath "/path/to/worktree"))
(allow file-write* (subpath "/private/tmp"))

; PTY (restricted to /dev/ptmx and ttys device files only)
(allow file-read* file-write* (literal "/dev/ptmx") (regex #"^/dev/ttys"))
```

---

## Recommended Fix for Worktree Settings

Update `.claude/settings.json` in worktrees to add read restrictions:

```json
{
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowWrite": ["./", "//tmp"],
      "denyRead": ["/"],
      "allowRead": [
        "./",
        "//tmp",
        "/usr",
        "/System",
        "/Library",
        "/bin",
        "/private/var",
        "/private/etc"
      ]
    },
    "network": {
      "allowedDomains": ["localhost", "127.0.0.1"]
    }
  }
}
```

**Caveats:**
- The `allowRead` list may need to be expanded depending on what tools the agent uses (e.g., git needs access to `/usr/share`, some tools need `/opt/homebrew`, etc.)
- `denyRead: ["/"]` blocks `getcwd` in shells whose working directory is outside the allow list — not a problem if the shell is `cd`'d into the worktree
- `//tmp` in settings resolves to `/private/tmp` on macOS (the `/tmp` symlink target)

---

## What the Original Report Got Wrong

| Claim | Reality |
|-------|---------|
| "No base deny" | Wrong — `(deny default)` is line 2 |
| "Rule ordering matters — allows before denies is broken" | Wrong — SBPL uses most-specific-wins; order is irrelevant for different-specificity rules |
| "Following denies can only block whole areas, no ability for exceptions" | Wrong — more-specific allows inside broader denies work correctly |
| "Sandbox doesn't block outside access" | **Correct** — but the reason is that `allowWrite` alone does not restrict reads |

---

## Tools and Functions Reference

| Symbol | Name | Role |
|--------|------|------|
| `Zx4` | profile assembler | Builds the complete SBPL profile string |
| `Rx4` | read rule generator | Generates `; File read` rules from readConfig |
| `Gx4` | write rule generator | Generates `; File write` rules from writeConfig |
| `gtq` | unlink deny generator | Generates `(deny file-write-unlink ...)` for denyWithinAllow paths |
| `Btq` | macOS sandbox wrapper | Wraps a command with `sandbox-exec -p <profile>` |
| `Jx4` | Linux sandbox wrapper | Wraps a command with `bwrap` |
| `Vx4` / `getFsReadConfig` | read config getter | Reads `denyRead`/`allowRead` from `d4` |
| `Sx4` / `getFsWriteConfig` | write config getter | Reads `allowWrite`/`denyWrite` from `d4`, prepends `anH()` defaults |
| `anH` | default safe paths | Returns `/dev/*`, `/tmp/claude`, `~/.claude/debug` |
| `yx4` / `initialize` | sandbox initializer | Validates deps, starts network proxy bridge |
| `d4` | parsed config | Global holding the active sandbox config |
| `CL` | path normalizer | Expands `~`, resolves symlinks, handles `/tmp`→`/private/tmp` |
| `dtq` | violation monitor | Streams macOS system log to surface sandbox deny events |
