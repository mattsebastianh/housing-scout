# Property AI Analyst — Prompt Reference

> **Live source:** the actual system prompt is the committed template
> **`agent_instructions/property_analyst.md`** (repo root). This document only
> describes how it is assembled and consumed — edit the template (or a local
> override), not this file, to change the analyst's behaviour.

## How the system prompt is built

`scout/core/analyse/prompt_builder.py::build_system_prompt("property_analyst", profile)`:

1. Loads `agent_instructions/property_analyst.local.md` if it exists (gitignored
   personal override), otherwise the committed `agent_instructions/property_analyst.md`.
2. Replaces the placeholders with values from the user's gitignored `profile.yaml`:

| Placeholder | Filled from |
|---|---|
| `{cities}` | `search.cities[].name`, comma-joined |
| `{price_min}` / `{price_max}` | `search.price_min_eur` / `search.price_max_eur` (dot-formatted) |
| `{property_type}` | `search.property_type` |
| `{preferred_plot_m2}` | `search.preferred_plot_m2` |
| `{buyer_profile}` | `compose_buyer_profile(profile.buyer)` — household, purpose, priorities, investment angle/notes, must-haves, deal-breakers, extra notes |
| `{response_language}` | `buyer.response_language` |

No personal or city literals live in code or in the committed template — they
arrive only at runtime from the profile.

---

## Model configuration

| Parameter | Value |
|---|---|
| Model | `gpt-5.4-mini` (override: `SCOUT_ANALYST_MODEL`) |
| Reasoning effort | `low` |
| Max completion tokens | `1500` |

Called concurrently for **all new scored listings** by
`scout/core/analyse/property_analyst.py::analyse_top(scored, profile)`; skipped
silently when `OPENAI_API_KEY` is absent.

---

## User prompt (per property)

Built dynamically from `ScoredListing` in
`scout/core/analyse/property_analyst.py::_build_prompt()`. Fields included:

```
**Propiedad:** {municipality}, {province}
**Precio:** {price_eur} € · {size_m2} m² · {price_psqm} €/m²
**Parcela:** {plot_m2} m²  (or — if unknown)
**Habitaciones:** {bedrooms} hab / {bathrooms} baños
**En mercado:** {days_on_market} días
**Puntuación compuesta:** {composite}/10
**Dimensiones:** precio: {score}; localización: {score}; desplazamiento: {score}; legal/catastral: {score}; regulatorio: {score}; ambiental: {score}; vecindario: {score}; infraestructura: {score}
**Descripción (extracto):** {first 400 chars of listing description}
```

### Dimension label mapping

| Internal key | Label in prompt |
|---|---|
| `price` | precio |
| `location` | localización |
| `commute` | desplazamiento |
| `legal` | legal/catastral |
| `regulatory` | regulatorio |
| `environmental` | ambiental |
| `neighbourhood` | vecindario |
| `infrastructure` | infraestructura |

---

## Output contract

The template instructs the model to respond in `{response_language}` with a
leading `SUMMARY:` paragraph (`RESUMEN:` in the Spanish template) followed by a
~180-word bullet analysis (connectivity, residential character, plot,
investment potential, price vs. market, pre-visit alerts).

The response is split by `_split_summary()` in `property_analyst.py`, which
recognises both the `SUMMARY:` and `RESUMEN:` markers:

- **Leading paragraph** — extracted and stored in `ScoredListing.summary_md`;
  surfaced in the Telegram card per property.
- **Remaining bullets** — stored in `ScoredListing.analyst_md`; included in the
  Markdown report.

If neither marker is present, the first paragraph becomes the summary and the
full text is kept as the analysis.

---

## Customising

- **Repo-wide change:** edit `agent_instructions/property_analyst.md` (English,
  default) or `agent_instructions/property_analyst.es.md` (Spanish backup, not
  loaded automatically — copy it over `property_analyst.md` or into a
  `.local.md` override to use it). Keep the placeholders and the
  `SUMMARY:`/`RESUMEN:` output contract intact — the Telegram card and report
  renderer depend on it.
- **Personal change:** create `agent_instructions/property_analyst.local.md`
  (gitignored); it takes precedence over the committed template.
- **Buyer-profile change:** edit `profile.yaml` (or re-run
  `python -m scout setup`) — the `{buyer_profile}` block is rebuilt from it on
  every run.
