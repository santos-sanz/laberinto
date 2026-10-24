# Laberinto: carrera de LLMs por un laberinto

Dos familias de modelos resuelven el mismo laberinto perfecto al mismo tiempo:

- **Carril de texto** — un modelo de chat de Nam recibe el laberinto y devuelve la ruta completa como JSON.
- **Carril de decisiones** — un modelo `output_modalities=decisions` de OpenRouter elige, cruce a cruce, la siguiente dirección. El harness ejecuta el movimiento y retrocede en los callejones sin salida.

La interfaz muestra en vivo el avance de cada modelo sobre el laberinto, el reloj de carrera, los pasos, las celdas visitadas, las llamadas, los tokens y la eficiencia de la ruta. La primera ruta que pasa el verificador gana.

Por defecto: laberinto **31×31**, texto `deepseek-v4-flash` (Nam) y decisiones `baseten/mammoth-1:free` (OpenRouter).

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

## Cómo funciona la carrera

1. El servidor genera un laberinto perfecto determinista a partir de `width`, `height` y `seed` (DFS aleatorio con semilla).
2. El solver BFS calcula la ruta óptima y se usa como referencia, no como respuesta. Por defecto el circuito es de 31×31.
3. Los dos carriles arrancan a la vez sobre el mismo laberinto.
4. Un carril termina cuando su ruta pasa `verify_path`: empieza en `(0,0)`, termina en `(width-1, height-1)`, cada salto es de una celda y no atraviesa paredes.
5. El reloj de cada carril se detiene al verificar su primera ruta. Gana el carril con menor `elapsed_ms`; si la diferencia es menor de 1 ms, hay empate.
6. Los dos carriles se dejan terminar para poder comparar rutas, incluso después de que haya ganador.

### Carril de texto (Nam)

- Pide **una ruta completa** en JSON: `{"path": [[x, y], ...]}`.
- El prompt incluye el laberinto como **lista de adyacencia** por celdas (`x,y:nesw`). En las pruebas, el ASCII clásico hacía que los modelos de razonamiento gastaran miles de tokens contando paredes; la adyacencia es mucho más fiable.
- Por defecto hace 2 intentos con feedback del verificador y un presupuesto de 16 384 tokens de completion, para que los modelos con razonamiento tengan espacio para pensar y emitir el JSON final.
- Si el contenido final llega vacío, también intenta extraer el JSON del campo de razonamiento.

### Carril de decisiones (OpenRouter)

- Usa `POST https://openrouter.ai/api/alpha/decisions`, no chat completions.
- En cada **cruce** (celda con más de una salida no visitada) envía una pregunta `choice` con todas las salidas legales. El modelo devuelve una probabilidad por dirección.
- En los pasillos con una sola salida el harness avanza sin llamar al modelo.
- Si el modelo elige una rama que acaba en callejón sin salida, el harness retrocede hasta el último cruce y vuelve a preguntar con el conjunto actualizado de celdas visitadas.
- El harness hace toda la navegación y el backtracking. El resultado es **modelo + harness**, igual que en `wu-card-game`; no es una medida de precisión pura del modelo.
- El presupuesto `max_junction_calls` limita las llamadas. Al agotarse, el harness usa una heurística BFS libre de modelo para terminar la ruta.

### Carril de control

La opción **Lane control** añade un tercer carril con `harness/heuristic`: la misma búsqueda y backtracking que el carril de decisiones, pero ordenando las salidas por distancia BFS al objetivo en lugar de preguntar a un modelo. Sirve para aislar lo que aporta el modelo. No compite por el primer puesto.

## Qué muestra la interfaz

- **Vista previa del circuito** con ruta óptima, callejones y cruces.
- **Dos carriles en vivo** (o tres con el control): laberinto, celdas visitadas, rastro de movimientos, ruta actual, posición animada y meta.
- **Reloj de carrera** y reloj por carril.
- **Métricas**: pasos, celdas, llamadas y tokens.
- **Comparador**: ganador, delta, velocidad relativa, pasos y eficiencia de cada ruta.
- **Registro de eventos** con trazas de ambos modelos.
- **Archivo** de carreras guardadas; al pulsar una se carga su estado final.
- **Repetir ruta** vuelve a animar las rutas terminadas.
- **Modo presentación**: botón **Presentar**, tecla `F` o `?present=1`. Oculta la configuración, agranda los laberintos y mantiene los controles esenciales. Añade `&race=<id>` para abrir una carrera guardada en presentación.
- **Pantalla completa** desde la barra de presentación.
- La carrera se transmite por **SSE** (`/api/races/{id}/stream`) con fallback a polling.

## API HTTP

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/api/bootstrap` | estado de claves, catálogos de modelos y valores por defecto |
| `GET` | `/api/maze?width=31&height=31&seed=42` | laberinto, ruta óptima y estadísticas |
| `POST` | `/api/races` | crea y arranca una carrera |
| `GET` | `/api/races/{id}` | estado actual (polling) |
| `GET` | `/api/races/{id}/stream` | stream SSE del estado en vivo |
| `POST` | `/api/races/{id}/cancel` | cancela una carrera en curso |
| `GET` | `/api/races` | resumen de carreras recientes |
| `GET` | `/api/export/{id}` | JSON completo guardado de una carrera |

Ejemplo de carrera:

```bash
curl -s -X POST http://127.0.0.1:8050/api/races \
  -H 'Content-Type: application/json' \
  -d '{
    "width": 31,
    "height": 31,
    "seed": 42,
    "text_model": "deepseek-v4-flash",
    "decisions_model": "baseten/mammoth-1:free",
    "text_max_attempts": 2,
    "max_junction_calls": 80,
    "include_baseline": false
  }'
```

## CLI

```bash
# imprimir un laberinto y su ruta óptima (31×31 por defecto)
uv run maze generate --seed 42

# ver también las coordenadas de la ruta
uv run maze generate --seed 42 --show-path

# carrera headless
uv run maze race --seed 42 \
  --text-model deepseek-v4-flash \
  --decisions-model baseten/mammoth-1:free

# carrera corta de 13×13 con el modelo de decisiones que probamos primero
uv run maze race --width 13 --height 13 --seed 42 \
  --decisions-model typesafe/jev-1.14

# probar el carril de decisiones sin API
uv run maze race --seed 42 --decisions-model harness/heuristic
```

## Estructura

```
maze/
  game.py       generación del laberinto, BFS, verificación de rutas
  prompts.py    prompt de texto, parser de rutas, request de Decisions
  clients.py    cliente de chat de Nam, cliente Decisions de OpenRouter
  runners.py    carril de texto, carril de decisiones, control heurístico
  models.py     configuración y estado de carriles
  race.py       orquestación, ganador, persistencia, historial
  server.py     FastAPI, SSE, estáticos
  cli.py        comando `maze`
web/            interfaz vanilla HTML/CSS/JS con canvas
tests/          laberinto, verificación, prompts, runners y carrera completa
scripts/        reinicio del servidor
results/        carreras guardadas (git-ignored)
```

## Tests

```bash
uv run pytest
```

La suite cubre generación determinista y conectividad del laberinto, simetría de paredes, ruta óptima, rechazo de cruces de pared y saltos, parsing de JSON y movimientos, prompt de adyacencia, carril de texto con un cliente falso, carril de decisiones con una política oráculo, control heurístico sin llamadas y una carrera completa por el manager.

## Ejemplo de ejecución

Con los valores por defecto, laberinto 31×31 semilla 42 (ruta óptima: 288 pasos):

- Decisiones con `baseten/mammoth-1:free`: ruta verificada en ~14 s, 22 llamadas, 4 callejones sin salida, 8 retrocesos, 100 % de eficiencia.
- Texto con `deepseek-v4-flash`: depende del presupuesto de razonamiento. En 31×31 el modelo puede consumir todo el completion razonando la ruta completa y no emitir el JSON.

Para una carrera corta y cómoda con el carril de texto, usa 13×13. Con `deepseek-v4-flash` y `typesafe/jev-1.14`, semilla 42 (42 pasos):

- Decisiones: ruta verificada en ~0,7 s, 2 llamadas, 100 % de eficiencia.
- Texto: ruta verificada en ~39–45 s, 1 intento, 100 % de eficiencia.

Los tiempos dependen del proveedor y del modelo elegido.

## Limitaciones conocidas

- La API Decisions de OpenRouter es alpha; su catálogo y su formato pueden cambiar.
- Los modelos de texto reciben el laberinto como adyacencia y devuelven la ruta completa; no es un agente multi-turno.
- El carril de decisiones depende del harness para moverse, retroceder y verificar. Repórtalo como **modelo + harness**.
- El control heurístico no compite por el ganador.
- El tamaño por defecto es 31×31. En mallas grandes los modelos de razonamiento pueden agotar su presupuesto de completion intentando resolver la ruta completa; para carreras cortas baja a 13×13 o usa el carril de control heurístico.
- Un laberinto más grande implica prompts más largos; el prompt de 31×31 ronda los 2 500 tokens de entrada.
- `.env` no se versiona. Nunca subas claves al repositorio.
