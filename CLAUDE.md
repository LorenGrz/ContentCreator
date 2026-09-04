# Contexto del proyecto

Bot serverless que lee actividad real de GitHub (y opcionalmente Google
Calendar), redacta borradores cortos de Twitter/X y un post de LinkedIn, y los
manda a un chat de Telegram con botones **Aprobar / Descartar**. **Nunca
publica solo** — la publicación siempre la hace Loren a mano después de
aprobar/editar el borrador.

- Corre una vez al día por schedule (EventBridge) y también on-demand:
  mandarle un mensaje al bot en Telegram dispara una corrida ya, usando el
  texto del mensaje como steering (`user_note`) para el modelo.
- Todos los días saca al menos un tweet con onda "tech news" (Hacker News,
  `AlwaysTechNews`, on por default) y al menos un borrador de LinkedIn
  (`LinkedinAlways`, on por default) — un gate basado en reglas (PR
  mergeado, repo nuevo, evento de calendario) decide si se enmarca como post
  sustancial o como reflexión corta.
- Puede seguir cuentas de X/Twitter vía un bridge RSS de Nitter (`XEnabled`,
  **off por default** — las instancias de Nitter son inestables). Si un
  borrador se apoya en un tweet seguido, propone un quote tweet en vez de un
  post original.
- Flujo de edición en Telegram: **Aprobar** → **Editar** con lenguaje natural
  ("más corto", "sacá el emoji") → Bedrock reescribe → vuelve con los mismos
  botones. **Copiar** usa el botón nativo de Telegram (tope 256 caracteres);
  si el texto es más largo, solo queda "Abrir en X" + el texto seleccionable.

## Stack

- Python 3.13, AWS Lambda `arm64`, **una sola función monolítica**.
- FastAPI + Mangum (`handler.py` rutea los eventos de EventBridge Scheduler
  directo al job diario; todo lo demás va a FastAPI).
- DynamoDB: una tabla, `PAY_PER_REQUEST`, `pk`/`sk` genérico, sin GSI.
- Amazon Bedrock (`strands-agents`) para generar los borradores — mismo
  patrón que usa `prioria`.
- SSM Parameter Store (SecureString) para secrets — **no** Secrets Manager
  (ahorra ~$0.40/secret/mes).
- SAM para packaging/deploy. Sin Docker para desarrollo local (`moto` para
  tests de storage, AWS real para iterar Bedrock/deploy).

## Última revisión

2026-09-04 — primera vez que se documenta en CLAUDE.md.
