# Laberinto: carrera de LLMs por un laberinto

Modelos de lenguaje resuelven el mismo laberinto perfecto al mismo tiempo. Hay dos modos de carrera:

- **Decisiones vs decisiones** (por defecto) — dos modelos `output_modalities=decisions` de OpenRouter navegan el laberinto cruce a cruce. El harness mueve la ficha, retrocede en los callejones y verifica la ruta.
- **Texto vs decisiones** — un modelo de chat de Nam recibe el laberinto y devuelve la ruta completa como JSON; un modelo de decisiones navega como arriba.

La interfaz muestra en vivo el avance de cada modelo sobre el laberinto, el reloj de carrera, los pasos, las celdas visitadas, las llamadas, los tokens y la eficiencia de la ruta. La primera ruta que pasa el verificador gana.

Por defecto: laberinto **255×255**, semilla 42, modo **Decisiones vs decisiones**, con `baseten/mammoth-1:free` y `baseten/elephant-1:free`. Se admiten laberintos de **5×5 a 255×255**.

Inspirado en [`wu-card-game`](https://github.com/santos-sanz/wu-card-game), adaptado de un juego de cartas aritmético a una carrera de navegación por laberintos.

## Inicio rápido

```bash
cp .env.example .env        # rellena NAN_API_KEY y OPENROUTER_API_KEY
uv sync
./scripts/restart.sh        # http://127.0.0.1:8050
```

También puedes arrancar el servidor en primer plano:

```bash
uv run maze serve --port 8050
```

La UI comprueba las dos claves al cargar. Si una clave falta o caduca, el carril correspondiente muestra el error del proveedor. El modelo especial `harness/heuristic` permite probar el carril de decisiones sin llamar a OpenRouter.

## Modos de carrera

### Decisiones vs decisiones

- Se eligen dos modelos de decisiones (A y B) y ambos corren sobre el mismo laberinto.
- Cada carril usa su propio `OpenRouterPolicy`; no hay carril de texto.
- El ganador es el carril con menor tiempo hasta una ruta verificada.
- Opcionalmente se puede añadir el **carril control** heurístico, que no compite por el primer puesto.
- Es el modo por defecto para aprovechar el tamaño 255×255, donde una ruta completa de texto es demasiado larga para el presupuesto de un modelo.

### Texto vs decisiones

- El carril de texto pide la ruta completa a Nam.
- El carril de decisiones navega cruce a cruce con OpenRouter.
- Solo se admite hasta **400 celdas** (aproximadamente 20×20) en el carril de texto. Para mallas mayores el carril se marca como no resuelto al instante y se recomienda usar el modo de decisiones. Así se evita lanzar prompts enormes condenados a fallar.

## Cómo funciona la carrera

1. El servidor genera un laberinto perfecto determinista a partir de `width`, `height` y `seed` (DFS aleatorio con semilla).
2. El solver BFS calcula la ruta óptima y se usa como referencia, no como respuesta.
3. Los carriles arrancan a la vez sobre el mismo laberinto.
4. Un carril termina cuando su ruta pasa `verify_path`: empieza en `(0,0)`, termina en `(width-1, height-1)`, cada salto es de una celda y no atraviesa paredes.
5. El reloj de cada carril se detiene al verificar su primera ruta. Gana el carril con menor `elapsed_ms`; si la diferencia es menor de 1 ms, hay empate.
6. Los carriles se dejan terminar para poder comparar rutas, incluso después de que haya ganador.

### Carril de texto (Nam)

- Pide **una ruta completa** en JSON: `{"path": [[x, y], ...]}`.
- El prompt incluye el laberinto como **lista de adyacencia** por celdas (`x,y:nesw`). En las pruebas, el ASCII clásico hacía que los modelos de razonamiento gastaran miles de tokens contando paredes; la adyacencia es mucho más fiable.
- Hace 2 intentos con feedback del verificador y un presupuesto de 16 384 tokens de completion.
- Si el contenido final llega vacío, también intenta extraer el JSON del campo de razonamiento.
- Para mallas de más de 400 celdas no se llama al modelo: el carril se cierra como `unsolved` con un mensaje explicativo.

### Carril de decisiones (OpenRouter)

- Usa `POST https://openrouter.ai/api/alpha/decisions`, no chat completions.
- En cada **cruce** (celda con más de una salida no visitada) envía una pregunta `choice` con todas las salidas legales. El modelo devuelve una probabilidad por dirección.
- El estado enviado es compacto: tamaño del laberinto, posición, objetivo, cola de la ruta actual, número de celdas visitadas y salidas legales con su **distancia exacta restante al objetivo** calculada por el harness.
- En los pasillos con una sola salida el harness avanza sin llamar al modelo.
- Si el modelo elige una rama que acaba en callejón sin salida, el harness retrocede hasta el último cruce y vuelve a preguntar con el conjunto actualizado de celdas visitadas.
- El presupuesto `max_junction_calls` limita las llamadas. Al agotarse, el harness usa una heurística BFS para terminar la ruta.
- Si OpenRouter responde `429` (límite de peticiones del plan gratuito), ese carril deja de llamar al modelo y continúa con la heurística. La carrera no se rompe.
- El harness hace el movimiento, el retroceso y la verificación. El resultado es **modelo + harness**, igual que en `wu-card-game`; no es una medida de precisión pura del modelo.

### Carril de control

La opción **Carril control** añade un carril con `harness/heuristic`: la misma búsqueda y backtracking que un carril de decisiones, pero ordenando las salidas por distancia BFS al objetivo en lugar de preguntar a un modelo. Sirve para aislar lo que aporta el modelo. No compite por el primer puesto.

## Qué muestra la interfaz

- **Selector de modo**: Decisiones vs decisiones o Texto vs decisiones.
- **Vista previa del circuito** con ruta óptima, callejones y cruces.
- **Dos carriles en vivo** (o tres con el control): laberinto, celdas visitadas, rastro de movimientos, ruta actual, posición animada y meta.
- **Reloj de carrera** y reloj por carril.
- **Métricas**: pasos, celdas, llamadas y tokens.
- **Comparador**: ganador, delta, velocidad relativa, pasos y eficiencia de cada ruta.
- **Registro de eventos** con trazas de cada modelo.
- **Archivo** de carreras guardadas; al pulsar una se carga su estado final.
- **Repetir ruta** vuelve a animar las rutas terminadas.
- **Modo presentación**: botón **Presentar**, tecla `F` o `?present=1`. Oculta la configuración, agranda los laberintos y mantiene los controles esenciales. Añade `&race=<id>` para abrir una carrera guardada en presentación.
- **Pantalla completa** desde la barra de presentación.
- La carrera se transmite por **SSE** (`/api/races/{id}/stream`) con fallback a polling.

### Laberintos grandes

- Las paredes se envían empaquetadas en base64 (4 bits por celda) y la lista de celdas visitadas se recorta en las respuestas públicas para que el SSE siga siendo ligero.
- El canvas cachea las paredes en una capa offscreen; no redibuja 65 000 celdas en cada frame.
- En mallas grandes la ruta se dibuja como una línea de color sobre una textura de paredes muy tenue. Es una vista de escala, no un plano celda a celda.

## API HTTP

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/api/bootstrap` | estado de claves, catálogos de modelos y valores por defecto |
| `GET` | `/api/maze?width=255&height=255&seed=42` | laberinto, ruta óptima y estadísticas |
| `POST` | `/api/races` | crea y arranca una carrera |
| `GET` | `/api/races/{id}` | estado actual (polling) |
| `GET` | `/api/races/{id}/stream` | stream SSE del estado en vivo |
| `POST` | `/api/races/{id}/cancel` | cancela una carrera en curso |
| `GET` | `/api/races` | resumen de carreras recientes |
| `GET` | `/api/export/{id}` | JSON completo guardado de una carrera |

Carrera de decisiones por defecto:

```bash
curl -s -X POST http://127.0.0.1:8050/api/races \
  -H 'Content-Type: application/json' \
  -d '{
    "width": 255,
    "height": 255,
    "seed": 42,
    "mode": "decisions",
    "decisions_models": [
      "baseten/mammoth-1:free",
      "baseten/elephant-1:free"
    ],
    "max_junction_calls": 12,
    "include_baseline": false
  }'
```

Carrera texto vs decisiones:

```bash
curl -s -X POST http://127.0.0.1:8050/api/races \
  -H 'Content-Type: application/json' \
  -d '{
    "width": 13,
    "height": 13,
    "seed": 42,
    "mode": "versus",
    "text_model": "deepseek-v4-flash",
    "decisions_model": "typesafe/jev-1.14",
    "text_max_attempts": 2,
    "max_junction_calls": 12
  }'
```

## CLI

```bash
# imprimir un laberinto (255×255 por defecto; el ASCII se omite si es enorme)
uv run maze generate --seed 42

# imprimir también el ASCII completo aunque haya 65 025 celdas
uv run maze generate --seed 42 --ascii

# ver las coordenadas de la ruta óptima
uv run maze generate --width 13 --height 13 --seed 42 --show-path

# carrera headless de decisiones (modo por defecto)
uv run maze race --seed 42 \
  --mode decisions \
  --decisions-models "baseten/mammoth-1:free,baseten/elephant-1:free"

# carrera texto vs decisiones en un laberinto manejable
uv run maze race --width 13 --height 13 --seed 42 \
  --mode versus \
  --text-model deepseek-v4-flash \
  --decisions-model typesafe/jev-1.14

# probar el carril de decisiones sin API
uv run maze race --seed 42 --mode decisions \
  --decisions-models "harness/heuristic,harness/heuristic"
```

## Estructura

```
maze/
  game.py       generación del laberinto, BFS, verificación, empaquetado de paredes
  prompts.py    prompt de texto, parser de rutas, request compacta de Decisions
  clients.py    cliente de chat de Nam, cliente Decisions de OpenRouter
  runners.py    carril de texto, carril de decisiones, control heurístico, fallback 429
  models.py     configuración, modos y estado de carriles
  race.py       orquestación, ganador, persistencia, historial
  server.py     FastAPI, SSE, estáticos
  cli.py        comando `maze`
web/            interfaz vanilla HTML/CSS/JS con canvas y capas cacheadas
tests/          laberinto, verificación, prompts, runners y carreras completas
scripts/        reinicio del servidor
results/        carreras guardadas (git-ignored)
```

## Tests

```bash
uv run pytest
```

La suite cubre generación determinista y conectividad, simetría de paredes, ruta óptima, serialización compacta de 255×255, rechazo de cruces de pared y saltos, parsing de JSON y movimientos, carril de texto con un cliente falso, límite de tamaño del carril de texto, carril de decisiones con una política oráculo, retroceso desde un giro equivocado, control heurístico sin llamadas, configuración por defecto y carreras completas de ambos modos por el manager.

## Ejemplo de ejecución

Valores por defecto, laberinto 255×255 semilla 42 (ruta óptima: 6 062 pasos):

- `baseten/mammoth-1:free`: ruta verificada en ~4,54 s, 12 llamadas, 100 % de eficiencia.
- `baseten/elephant-1:free`: ruta verificada en ~4,14 s, 12 llamadas, 100 % de eficiencia.

Los tiempos dependen del proveedor, del plan gratuito y del modelo elegido. Si se agota el límite de peticiones, el carril continúa con la heurística.

## Limitaciones conocidas

- La API Decisions de OpenRouter es alpha; su catálogo y su formato pueden cambiar.
- En 255×255 la visualización es una vista de escala: la ruta es legible, pero no se distinguen paredes celda a celda.
- Los modelos gratuitos pueden compartir un límite de peticiones por minuto. El fallback a heurística evita que la carrera falle, pero reduce la contribución del modelo en ese carril.
- El carril de decisiones recibe la distancia exacta al objetivo de cada salida legal. Es **modelo + harness**, no una medida de precisión pura.
- El carril de texto solo se usa en mallas de hasta 400 celdas; para laberintos grandes el modo adecuado es Decisiones vs decisiones.
- El control heurístico no compite por el ganador.
- `.env` no se versiona. Nunca subas claves al repositorio.
