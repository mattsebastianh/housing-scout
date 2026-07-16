# Next Move — Initiation config wizard v2 (preferences, goals & agent behavior)

_Saved 2026-07-14. Status: **approach approved, not implemented**. Brainstormed in session `wizard-profile-buyer-approach`; a fresh session should pick this up by resuming `superpowers:brainstorming` (present the remaining design sections against this sketch), then `superpowers:writing-plans`, then implementation._

## Idea (user request)

An initiation/configuration flow that defines the user's preferences and goals at project setup time **and whenever re-invoked later**, helping the user configure the tool with custom requirements and shape the AI agents' behavior — including an interface to fill in the user's own prompt text/data.

## Decisions already made (2026-07-14, user-approved)

| Question | Decision |
|---|---|
| Interface | **Richer CLI wizard** — extend the existing `python -m scout setup`; no Telegram or web surface |
| Behavior scope | **Profile + custom prompts** — structured preference/goal fields plus freeform per-agent instruction text |
| Goals data | **Few structured fields + freeform** — small typed set to prompt thinking; prose feeds the AI |
| Mechanism | **Approach 1 approved:** custom prompt text is stored in `profile.yaml` and injected via a new `{custom_instructions}` placeholder in the committed templates. Approach 2 (wizard-generated `agent_instructions/*.local.md` copies) was considered and rejected: generated copies freeze the template at generation time and round-trip editing is fragile. The `.local.md` full-override path stays untouched for power users. |

## Design sketch (to be refined into a spec in the new session)

- **Profile model** (`scout/core/profile.py`) — both new sections optional/defaulted, so existing `profile.yaml` files keep loading:
  - `ProfileGoals`: `goals: list[str] = []` (e.g. "move in < 12 months", "rental yield ≥ 5%"), `timeline: str = ""`, `budget_flexibility: str = ""`
  - `ProfileAgents`: `analyst_instructions: str = ""`, `chat_instructions: str = ""`
  - `Profile` gains `goals: ProfileGoals` and `agents: ProfileAgents`
- **Templates** — `agent_instructions/property_analyst.md` and `chat_agent.md` each gain a `{custom_instructions}` placeholder (renders empty when unset); `prompt_builder.build_system_prompt` fills it from the matching `ProfileAgents` field; `compose_buyer_profile` folds the structured goals into the `{buyer_profile}` prose.
- **Wizard** (`scout/core/setup_wizard.py`) — refactor into sections: `search`, `buyer`, `goals`, `agents`.
  - **Re-runnable / edit mode:** if `profile.yaml` exists, load it and show every current value as the editable default (Enter keeps it).
  - **Section selection:** `python -m scout setup [search|buyer|goals|agents]` runs one section and rewrites `profile.yaml`; no arg runs all sections.
  - **Multi-line input** for the two agent-instruction prompts (finish with an empty line).
- **Entry points** — `python -m scout setup` / `run_setup.py` keep their names; first-run gate (exit 2) unchanged.
- **Tests (TDD)** — profile back-compat (old YAML without new sections loads); `{custom_instructions}` filled and empty cases; wizard edit mode keeps existing values on blank answers; single-section run leaves other sections intact; multi-line capture; write→load roundtrip.
- **Docs afterwards** — README ("Customising the AI instructions", Setup) and CLAUDE.md (commands, key files) updated to describe the sectioned, re-runnable wizard.

## Estimated effort

~1 day including tests. Purely additive: profile file + wizard + one placeholder; no pipeline or DB changes.

---

# Previous move — Telegram-Triggered On-Demand Scout

_Saved 2026-07-07. Status: **implemented 2026-07-07** on branch `feat/telegram-on-demand-scout`. Related: ROADMAP.md Tier 3.3 (interactive Telegram bot) — this is its first, smallest slice._

_Update 2026-07-14: publication decision — the template goes public as a **fresh HEAD-only repository** (the old repo stays private); the previously planned git history rewrite is superseded._

## Idea

Trigger a scout run by sending the bot a Telegram message (e.g. `/scout`), **only when explicitly asked**. The weekly launchd schedule stays exactly as is — this adds a second, on-demand entry point to the same pipeline.

## How it would work

1. A small listener long-polls the Telegram `getUpdates` API (`timeout=50`, so near-zero request volume) using the existing `TELEGRAM_BOT_TOKEN`.
2. On a message from the authorised chat matching the command grammar, it replies immediately ("🔍 Buscando nuevas propiedades…") and kicks off the normal pipeline (`orchestrate.run_once()` / `run_daily.py`).
3. Results arrive through the existing notify flow: stats header + per-property cards + `.md` report document. No changes to scrape/filter/enrich/score/report stages.

### Command grammar — flexible city selection

| Message | Action |
|---|---|
| `/scout` | Run **all** configured cities |
| `/scout <city>` | Run that city only |
| `/scout <city1> <city2>` / `/scout <city1>, <city2>` | Run any subset — space- or comma-separated |
| `/scout <unknown city>` | Reply with the list of valid cities, run nothing |
| anything else | Ignored |

City matching is case- and accent-insensitive and tolerates the `/scout@BotName` form Telegram uses in groups. Valid cities come from the configured city list, so adding a city there automatically extends the command.

## Safeguards (all required)

- **Auth**: only process updates where `message.chat.id == TELEGRAM_CHAT_ID`; silently ignore everyone else.
- **Offset persistence**: store the last processed `update_id` (small state file or DB table) so a listener restart never re-triggers old commands.
- **Concurrency lock**: a lockfile shared with the scheduled run; if a run is already in progress reply "⏳ Ya hay una búsqueda en curso" instead of double-running.
- **Credit awareness**: a full run costs ~30 Bright Data credits per configured city (5,000/month free tier), so even frequent manual runs are safe; an optional configurable cooldown can be added later if needed.

## Implementation sketch

- New module `scout/core/notify/listener.py` (implemented pre-rename as `chalet/notify/listener.py`): async long-poll loop, command parse (multi-city), auth filter, dispatch. Reuses `_post()` from the Telegram notifier for replies. Entry point `run_listener.py` at repo root, mirroring `run_daily.py`.
- Dispatch runs the pipeline as a **subprocess** (`.venv/bin/python run_daily.py --city <city1> --city <city2>`): a pipeline crash never kills the listener, and memory is released after each run. `run_daily.py` gains a repeatable `--city` flag.
- Shared lock: small `runlock.py` helper (pidfile with stale-lock reclaim) acquired by `run_daily.py` itself, so manual and scheduled runs can never overlap regardless of which side starts first.
- Runs as a second launchd job with `KeepAlive: true`; the weekly plist is untouched. Installing/removing that job is the on/off switch — no config toggle needed.
- Tests: respx-mocked `getUpdates`/`sendMessage` (auth filter, command parse incl. multi-city and unknown-city reply, offset advance), lockfile behaviour, subset vs all-cities dispatch args.

### Alternatives considered

- **Periodic poll every N min** (cron-style instead of daemon): simpler but adds up-to-N-min latency and pointless wakeups. Long polling is cheaper and instant.
- **Webhook**: needs a public HTTPS endpoint — not viable on a home Mac without a tunnel. Rejected.

## Estimated effort

~half a day including tests. No schema or pipeline changes; purely additive.

## Extension (2026-07-07): conversational chat agent

Implemented alongside: non-command messages to the bot are answered by
the chat agent (`scout/core/notify/chat_agent.py`, OpenAI `gpt-5-nano`,
`reasoning_effort=minimal`, rolling 12-message history) so the chat stays
dynamic between runs. The agent knows the project context and is told when a
search is in progress; without `OPENAI_API_KEY` it falls back to a static
help reply — never silence.
