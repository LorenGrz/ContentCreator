# AGENTS.md

Single source of truth for humans and AI agents working on this repo. Moved here from CLAUDE.md on 2026-10-10 by `project-init`'s adopt mode - if this file and the code disagree, the code wins, fix this file.

## Documentation map (read this instead of the code)

1. `AGENTS.md` (this file) - map, how we work, workflow contract.
2. `.agents/CONTEXT.md` - current stack/architecture snapshot and repo facts.
3. `docs/plans/HANDOFF.md` - current state and how to resume, read first if work is mid-flight.
4. `docs/decisions/` - ADRs: why a non-trivial trade-off was decided the way it was.

# Contexto del proyecto

Bot serverless que lee actividad real de GitHub (y opcionalmente Google
Calendar), redacta borradores cortos de Twitter/X y un post de LinkedIn, y los
manda a un chat de Telegram con botones **Aprobar / Descartar**. **Nunca
publica solo** — la publicación siempre la hace Loren a mano después de
aprobar/editar el borrador.

- Corre una vez al día por schedule (EventBridge) y también on-demand:
  mandarle un mensaje al bot en Telegram dispara una corrida ya, usando el
  texto del mensaje como steering (`user_note`) para el modelo.
- Ingesta de GitHub con fallback a commit `head`: extrae eventos y commits
  reales de Loren (ej. StudyQuest, Roadmap, etc.), garantizando que la actividad
  personal siempre tenga prioridad.
- Todos los días saca al menos un tweet con onda "tech news" desde el [Weekly
  AI News Digest](https://elbruno.github.io/weekly-ai-news-digest/) con filtro
  estricto de diversidad de proveedores (tope de 1 noticia para Microsoft/Copilot)
  y al menos un borrador de LinkedIn (`LinkedinAlways`, on por default) — un gate
  basado en reglas decide si se enmarca como post sustancial o reflexión corta.
- Mix diario balanceado en prompts: Tweet 1 enfocado en trabajo/commit real de
  Loren, Tweet 2 en descubrimiento open-source (GitHub Trending / Hugging Face),
  Tweet 3 en debate/noticia tech, y regla anti-monopolio (prohibido repetir el
  mismo proveedor en más de un borrador por corrida).
- Puede seguir cuentas de X/Twitter vía un bridge RSS de Nitter (`XEnabled`,
  **off por default** — las instancias de Nitter son inestables). Si un
  borrador se apoya en un tweet seguido, propone un quote tweet en vez de un
  post original.
- Flujo de edición y aprobación en Telegram: al presionar **Aprobar**, el
  borrador pasa por un modelo superior (Tier 2: Claude Sonnet 4.6) que lo pule y
  eleva su ritmo y gancho técnico manteniendo el contexto exacto antes de entregarlo.
  Luego permite **Editar** con lenguaje natural ("más corto", "sacá el emoji")
  reutilizando el modelo pro → vuelve con los mismos botones. **Copiar** usa el
  botón nativo de Telegram (tope 256 caracteres); si el texto es más largo, solo
  queda "Abrir en X" + el texto seleccionable.
- Deduplicación y triggers en Telegram: los `update_id` entrantes se reclaman
  atómicamente en DynamoDB para evitar repeticiones por reintentos de Telegram.
  El botón de edición es idempotente (no reenvía el prompt si la sesión ya
  está abierta). Palabras como "mandame recomendaciones", "dame recomendaciones"
  o "generar" interrumpen cualquier sesión de edición previa y disparan una
  generación limpia de borradores.

## Stack

- Python 3.13, AWS Lambda `arm64`, **una sola función monolítica**.
- FastAPI + Mangum (`handler.py` rutea los eventos de EventBridge Scheduler
  directo al job diario; todo lo demás va a FastAPI).
- DynamoDB: una tabla, `PAY_PER_REQUEST`, `pk`/`sk` genérico, sin GSI.
- Amazon Bedrock (`strands-agents`) con arquitectura de dos niveles:
  - Tier 1: Claude Haiku 4.5 (`BEDROCK_MODEL_ID`) para generación diaria rápida y económica de candidatos.
  - Tier 2: Claude Sonnet 4.6 (`BEDROCK_PRO_MODEL_ID`) para refinamiento al aprobar y ediciones interactivas.
- SSM Parameter Store (SecureString) para secrets — **no** Secrets Manager
  (ahorra ~$0.40/secret/mes).
- SAM para packaging/deploy. Sin Docker para desarrollo local (`moto` para
  tests de storage, AWS real para iterar Bedrock/deploy).

## Última revisión

2026-10-01 — refinamiento de borradores aprobados y ediciones con Claude Sonnet 4.6 en Bedrock.

## Workflow contract

These rules describe this repo's CURRENT reality, detected by `project-init`'s `adopt.sh` on 2026-10-10 - not an aspiration. If a row says "nothing (convention only)", that rule is not mechanically enforced today.

| Rule | Documented | Enforced by |
|---|---|---|
| Single branch flow - `main` is both base and release branch | this section | nothing (convention only) |
| Branch names observed: feat/ (3),fix/ (2) | this section | nothing (convention only) |
| PRs merged into `main` via merge commit (5 of last 17 commits are merges) | this section | nothing (convention only) |
| ~100% of the last 12 commit subjects on `main` are Conventional Commits | this section | nothing (convention only) |
| No CI configured | this section | nothing (convention only) |
| Repo allows: squash=true, merge-commit=true, rebase=true; delete-branch-on-merge=false | this section | GitHub repo settings (`gh repo view`) |

Changing any rule above: update this table and every enforcement point in the same change, and record it in `docs/decisions/`.

### Recommended (not enforced yet)
- Branch protection on `main` (required status checks, no force-push).
- CI that runs lint/typecheck/tests on every PR.


## Documentation rules

- Any decision with a real trade-off (architecture, a hard-to-reverse library/service choice, data model, security trade-off) gets a new ADR under the ADR directory above.
- When work pauses mid-flight, update `docs/plans/HANDOFF.md` before stopping, not after.
- A change that alters architecture, env vars, commands, or deploy updates `AGENTS.md` and `.agents/CONTEXT.md` in the same change.
- Changing any "Workflow contract" rule updates every enforcement point in the same change, per that section above.
