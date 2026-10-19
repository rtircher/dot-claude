# Routes to a cross-family reviewer

`full.md` points here when external review was requested but no reviewer could
run. Every route ends in an `EXTERNAL_REVIEWERS` entry that
`scripts/external-review.mjs` runs:

- **Hosted API**: an entry with the vendor's `baseUrl`, `model`, and
  `apiKeyEnv`, plus the key in the environment. Needs only `node`; the artifact
  goes to that vendor, so the skill's consent stop applies.
- **Local model**: Ollama or vLLM serving an OpenAI-compatible endpoint on
  hardware the user controls, as an entry with `"private": true` (no key, no
  consent stop).
- **Codex**: install the `codex` plugin, run `/codex:setup` (installs the
  `codex` CLI and logs in), then add `{"name":"codex","kind":"codex"}`. Diffs
  only.

**Major non-Claude families (as of mid-2026).** Any of these counts as a
cross-family vote; prefer whichever the user already has access to.

| Family | Cloud | Local (Ollama / vLLM) |
|--------|-------|------------------------|
| OpenAI | GPT-5.5 (what Codex runs; also reachable via the OpenAI API) | — |
| Google | Gemini 3.1 Pro | — |
| xAI | Grok 4.3 | — |
| Zhipu | GLM-5.2 (hosted API) | GLM-5.x open weights |
| Moonshot | Kimi K2.6 (hosted API) | K2.x open weights |
| DeepSeek | DeepSeek V4 (hosted API) | V4 open weights |
| Alibaba | Qwen 3.6 Plus (hosted API) | Qwen3-Coder |

On modest local hardware, a small coder model (e.g. Qwen 3.6 27B or Devstral
Small 2) is still an independent read: weaker, but fully on-machine, so the
consent stop never applies. The leaderboard churns quarterly; treat these as
defaults to reach for, and when a run matters, check the named family's
current flagship rather than assuming this table is fresh.

**Cloud sessions: skip the local-model path.** In a remote session (Claude Code
on the web), local models are usually impractical: the container is CPU-only
(a 7-8B model crawls; the flagships above won't run at all), ephemeral (the
multi-GB weights re-download every session), and the network policy typically
blocks the model registries (ollama.com, huggingface.co) outright. Prefer a
hosted API there: the shipped script plus a key in the environment's env vars,
with the vendor's domain allowed by the environment's network policy. The
privacy case for local is also moot in the cloud: the repo already lives in the
session container, so in-container Ollama keeps the no-egress property but
protects nothing the session hasn't already seen. Reserve the local-model path
for sessions on a real machine (GPU or Apple Silicon, persistent disk, code
that never left home).
