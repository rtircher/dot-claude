---
description: Provision a local Ollama-backed third-party reviewer (model sized to this machine) for adversarial-review and autonomous-feature
allowed-tools: Bash(bash:*), Bash(nvidia-smi:*), Bash(ollama:*), Bash(curl:*), Bash(jq:*), Bash(node:*), Bash(npm:*), Bash(opencode:*), Bash(systemctl:*), Read, Edit, Write
---

Set up the local-model path of the `adversarial-review` skill on this machine:
Ollama serving a coder model sized to the hardware, OpenCode as the agent
harness, and the `EXTERNAL_REVIEW_*` env vars that drive the skill's shipped
`external-review.mjs` reviewer. Everything runs on localhost, so third-party
review gains a cross-family vote without any artifact leaving the machine (and
therefore without the skill's consent stop).

Run every phase to completion; report measured numbers, not table values.

## 1. Probe the machine

```sh
bash "${CLAUDE_PLUGIN_ROOT}/scripts/probe-machine.sh"
```

Read the JSON before anything else. Decisions key off `gpu.vram_free_mb` (NOT
`vram_total_mb`: other tenants may already hold VRAM; check
`nvidia-smi --query-compute-apps=` to see who, and whether they are transient
or resident), `ram_gb`, `disk_free_gb`, and the container markers.

## 2. Environment gate

- **Cloud / ephemeral session** (`is_container` true, no systemd, or a Claude
  Code web session): stop. Local models are the wrong tool there; per the
  adversarial-review skill's cloud-session note, point the user at the shipped
  script plus a hosted-API key instead.
- **CPU-only machine** (`gpu.vendor` = none): a local model will be painfully
  slow. Recommend the hosted-API path; only proceed (with a 7-8B model) if the
  user insists after hearing that.
- Disk: budget roughly 20 GB per model plus headroom; refuse politely when
  `disk_free_gb` < 40.

## 3. Pick the model (verify, then trust)

Size against FREE VRAM, leaving 1-2 GB headroom for KV cache and CUDA overhead.
Starting table (as of mid-2026; the leaderboard churns quarterly, so before
pulling, list current tags via `curl -s https://ollama.com/library/<model>/tags`
and prefer whatever the named family's current best coder is):

| Free VRAM | Primary | Notes |
|-----------|---------|-------|
| >= 20 GB | `qwen3-coder:30b` | 30B-A3B MoE q4, ~18 GB weights |
| 16-20 GB | `qwen3-coder:30b` accepting partial CPU offload | MoE tolerates ~10-15% spill at usable speed; pull `devstral:24b` as fallback |
| 12-16 GB | `devstral:24b` | dense 24B q4, ~14 GB |
| 8-12 GB | `qwen2.5-coder:14b` | weaker but still an independent read |
| < 8 GB | hosted API instead | see step 2 |

Apple Silicon: treat ~70% of unified memory as the VRAM budget (the probe
already reports it that way).

## 4. Install and tune Ollama

Linux: `curl -fsSL https://ollama.com/install.sh | sh` (systemd service).
macOS: `brew install ollama && brew services start ollama`.

Then raise the defaults; the stock 4k context is useless for diff review. On
Linux, write a systemd drop-in (back up any existing override first):

```
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=32768"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_KEEP_ALIVE=10m"
```

`sudo systemctl daemon-reload && sudo systemctl restart ollama`, then confirm
`curl -s http://localhost:11434/api/version` answers. On macOS set the same
vars via `launchctl setenv`.

## 5. Pull, then MEASURE (the step that keeps the table honest)

`ollama pull <primary>` (and the fallback when the table says so). Then:

1. One warm-up generation (the first call pays a multi-minute cold load).
2. `ollama ps`: check the CPU/GPU split and that resident tenants still fit.
3. A realistic prompt (~2k tokens, e.g. a real diff) via `/api/generate`,
   reading `eval_count/eval_duration` and `prompt_eval_count/prompt_eval_duration`.

Acceptance: >= 20 tok/s generation and >= 300 tok/s prompt processing.
Below that, or GPU share under ~80%, drop one tier and re-measure. Report the
measured numbers to the user either way.

## 6. Install and pin OpenCode

`npm install -g opencode-ai` (needs node >= 18; the probe reports the major).
Write `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": { "<primary>": { "limit": { "context": 32768, "output": 8192 } } }
    }
  },
  "model": "ollama/<primary>"
}
```

If the user tracks dotfiles in a repo, put the config there and symlink it
following their pattern instead of writing the live file directly. Verify with
`opencode models` (the ollama entries must list) and one read-only run:
`opencode run --agent plan --model ollama/<primary> "one-sentence sanity check"`.

## 7. Wire the review-skill discovery

Add to the user's `settings.json` (their dotfiles copy when tracked):

```json
"env": {
  "EXTERNAL_REVIEW_BASE_URL": "http://localhost:11434/v1",
  "EXTERNAL_REVIEW_MODEL": "<primary>"
}
```

plus `Bash(ollama *)` and `Bash(opencode *)` permissions. Tell the user the env
block becomes ambient in NEW sessions only.

## 8. Smoke-test the real path

Run the adversarial-review skill's shipped reviewer on a real diff:

```sh
git diff HEAD~1..HEAD | \
  EXTERNAL_REVIEW_BASE_URL=http://localhost:11434/v1 EXTERNAL_REVIEW_MODEL=<primary> \
  node "${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts/external-review.mjs" \
    --type diff --target "HEAD~1..HEAD @ $(git rev-parse --short HEAD)"
```

Success = schema-valid JSON findings with the sha256 artifact binding. That is
exactly what the `dev-adversarial-review` workflow folds in when invoked with
`externalReview: true`.

## 9. Offer (do not impose) the standing default

Ask whether the user wants a standing pre-authorization in their CLAUDE.md, and
recommend the middle ground: `externalReview: true` by default for PR/diff
reviews only (cross-family reads pay off most there), spec/plan panels staying
Claude-only on request. Local model, so no consent ping either way. If they
accept, also write a memory entry naming the endpoint, model, and fallback so
future sessions discover the reviewer.

## Report

Close with: chosen model + measured tok/s and GPU split, fallback model if any,
what was written where, the new-session caveat for the env vars, and the
standing-default decision.
