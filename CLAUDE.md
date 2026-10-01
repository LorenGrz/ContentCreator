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
