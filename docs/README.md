# Documentation index

| Folder | Doc | What it is |
|---|---|---|
| `product/` | [PRD.md](product/PRD.md) | Product requirements — generic pipeline, profile-driven personalization, goals, constraints |
| `engineering/` | [ARCHITECTURE.md](engineering/ARCHITECTURE.md) | Pipeline internals, core/providers split, tech stack, external services |
| `engineering/` | [FEATURES.md](engineering/FEATURES.md) | Every implemented feature with status, known bugs, planned backlog |
| `planning/` | [ROADMAP.md](planning/ROADMAP.md) | Structural issues, confirmed bugs, prioritised feature backlog (agent review, 2026-06) |
| `planning/` | [NEXT_MOVE.md](planning/NEXT_MOVE.md) | Feature plans saved before implementation; status updated when shipped |
| `planning/` | [2026-07-13-genericize-and-personalize-plan.md](planning/2026-07-13-genericize-and-personalize-plan.md) | Implementation plan: genericize the template + personalize via profile.yaml |
| `prompts/` | [analyst_prompt.md](prompts/analyst_prompt.md) | Property AI Analyst prompt reference — how `agent_instructions/property_analyst.md` is assembled and consumed |
| `prompts/` | [agent_skill_prompt.md](prompts/agent_skill_prompt.md) | Template system prompt for a conversational Claude assistant skill |
| `prompts/` | [project_instructions.md](prompts/project_instructions.md) | Template project-instructions prompt for an AI assistant instance |
| `specs/` | [2026-07-07-brightdata-scraper-design.md](specs/2026-07-07-brightdata-scraper-design.md) | Design spec: Bright Data scrape-provider migration |
| `specs/` | [2026-07-13-genericize-and-personalize-design.md](specs/2026-07-13-genericize-and-personalize-design.md) | Design spec: generic housing-scout template + gitignored personal profile |

Related (outside `docs/`):

- **`agent_instructions/`** (repo root) — the *live* AI prompt templates (`property_analyst.md`, `chat_agent.md`) filled from `profile.yaml` at runtime; gitignored `*.local.md` overrides win. The `prompts/` docs above are references/templates, not the live source.
- **`profile.example.yaml`** (repo root) — template for the gitignored personal `profile.yaml` (created via `python -m scout setup`).

Conventions:

- **New design specs** go in `specs/` named `YYYY-MM-DD-<topic>-design.md`.
- **Feature ideas** land in `planning/NEXT_MOVE.md` first; when shipped, the status line at the top is updated instead of deleting the plan.
- `engineering/` docs describe what exists today; `planning/` docs describe what's next.
- **No personal data** (target cities, price range, buyer household) in committed docs — it belongs in `profile.yaml`.
