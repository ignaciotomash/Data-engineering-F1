# 🏎️ Plan: Ingeniería de Datos + ML con Fórmula 1

Proyecto de punta a punta: traer los datos de una API pública, modelarlos y usarlos para predecir resultados.

```
API Jolpica  ──►  raw (JSON)  ──►  DuckDB  ──►  dbt (staging → marts)  ──►  features  ──►  modelo ML  ──►  predicción
   Etapa 1                                           Etapa 2                         Etapa 3
```

| Etapa | Qué se hace | Duración |
|---|---|---|
| 1. Ingesta | Bajar la historia de la F1 (1950–hoy) y guardarla | 1 día |
| 2. Modelado | Ordenar los datos en un modelo analítico con dbt | 2 días |
| 3. Machine Learning | Predecir las chances de ganar de cada piloto | 1–2 días |

**Total: 4–5 días**

---

## 0. Preparación (1–2 horas)

### Qué instalar
- **Python 3.11+**
- **Git** y una cuenta de GitHub
- **VS Code** (o el editor que prefieras)
- **DBeaver** (opcional, para mirar la base de datos con una interfaz visual)

### Crear el proyecto
```bash
mkdir f1-data && cd f1-data
git init
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install requests pandas duckdb dbt-duckdb scikit-learn lightgbm
```

### Estructura de carpetas
```
f1-data/
├── data/
│   ├── raw/              # JSON tal cual llega de la API (nunca se modifica)
│   └── f1.duckdb         # la base de datos
├── ingestion/
│   └── extract.py        # Etapa 1
├── f1_dbt/               # Etapa 2 (lo crea dbt init)
│   └── models/
│       ├── staging/
│       ├── marts/
│       └── ml/
├── ml/
│   ├── train.py          # Etapa 3
│   └── predict.py
├── .gitignore            # agregar: .venv/, data/
└── README.md
```

> 💡 **Por qué DuckDB:** es una base de datos que vive en un solo archivo, no hay que instalar un servidor y es muy rápida para análisis. Ideal para empezar.

---

## Etapa 1 — Ingesta: la historia de la F1 en tu base (1 día)

**Objetivo:** tener en tu base de datos todos los resultados, pilotos, equipos y circuitos desde 1950.

**Fuente:** API Jolpica-F1 (sucesora de Ergast), gratis y sin API key.
URL base: `https://api.jolpi.ca/ergast/f1/`

### Paso 1 — Explorar la API (30 min)
Abrí en el navegador y mirá qué devuelve cada endpoint:
- `https://api.jolpi.ca/ergast/f1/seasons.json`
- `https://api.jolpi.ca/ergast/f1/2024/races.json`
- `https://api.jolpi.ca/ergast/f1/2024/results.json`
- `https://api.jolpi.ca/ergast/f1/2024/qualifying.json`
- `https://api.jolpi.ca/ergast/f1/drivers.json`, `constructors.json`, `circuits.json`

Fijate en tres cosas:
1. Los datos vienen **anidados** (una carrera adentro tiene una lista de resultados).
2. La respuesta trae `total`, `limit` y `offset`: hay **paginación**.
3. Cada piloto, equipo y circuito tiene un **id de texto** (ej: `max_verstappen`, `red_bull`, `monza`).

### Paso 2 — Escribir el extractor (2–3 h)
En `ingestion/extract.py`, una función que:
1. Pida una página con `?limit=100&offset=0`.
2. Siga pidiendo y sumando 100 al `offset` hasta llegar al `total`.
3. Espere ~1 segundo entre pedidos (**respetar el límite de la API**).
4. Reintente si falla (por ejemplo, 3 intentos esperando un poco más cada vez).

Esqueleto:
```python
import time, json, requests
from pathlib import Path

BASE = "https://api.jolpi.ca/ergast/f1"

def fetch_all(endpoint: str) -> list[dict]:
    """Baja todas las páginas de un endpoint y devuelve la lista de páginas."""
    pages, offset = [], 0
    while True:
        r = requests.get(f"{BASE}/{endpoint}.json",
                         params={"limit": 100, "offset": offset}, timeout=30)
        r.raise_for_status()
        data = r.json()["MRData"]
        pages.append(data)
        offset += 100
        if offset >= int(data["total"]):
            return pages
        time.sleep(1)  # ser amable con la API
```

### Paso 3 — Guardar los datos crudos (30 min)
Guardá cada respuesta **tal cual** en `data/raw/`:
```
data/raw/results/season=2024.json
data/raw/qualifying/season=2024.json
data/raw/drivers.json
...
```
> 💡 **Regla de oro:** los datos crudos no se tocan nunca. Si mañana te equivocás limpiando, volvés a partir de acá sin tener que pedirle todo de nuevo a la API.

Agregá una lógica simple: **si el archivo de esa temporada ya existe, no lo vuelvas a bajar** (salvo la temporada actual, que sigue cambiando).

### Paso 4 — Aplanar y cargar en DuckDB (2 h)
Convertí el JSON anidado en tablas planas con pandas y cargalas en un esquema `raw`:

| Tabla | Una fila por… |
|---|---|
| `raw.drivers` | piloto |
| `raw.constructors` | equipo |
| `raw.circuits` | circuito |
| `raw.races` | carrera (temporada, ronda, fecha, circuito) |
| `raw.results` | piloto en cada carrera (largada, posición final, puntos, estado) |
| `raw.qualifying` | piloto en cada clasificación |

**Carga idempotente:** que correr el script dos veces no duplique filas. La forma más simple es borrar y volver a cargar la temporada:
```sql
DELETE FROM raw.results WHERE season = 2024;
INSERT INTO raw.results SELECT ... ;
```

### Paso 5 — Verificar (30 min)
Respondé estas preguntas con SQL. Si los números tienen sentido, la ingesta está bien:
- ¿Cuántas carreras hay por temporada?
- ¿Quién tiene más victorias en la historia?
- ¿Hay alguna carrera sin resultados?

### ✅ Checklist Etapa 1
- [ ] El extractor baja todas las temporadas con paginación
- [ ] El JSON crudo está guardado en `data/raw/`
- [ ] Las 6 tablas están cargadas en DuckDB
- [ ] Correr el script dos veces no duplica datos
- [ ] Primer commit a GitHub

**🎓 Qué aprendiste:** consumir una API real (paginación, límites, reintentos), separar los datos crudos de los limpios y hacer cargas idempotentes.

---

## Etapa 2 — Modelado con dbt (2 días)

**Objetivo:** convertir las tablas crudas en un modelo limpio, testeado y documentado, listo para analizar.

### Paso 1 — Configurar dbt (30 min)
```bash
dbt init f1_dbt
```
En `~/.dbt/profiles.yml`, apuntá a tu base:
```yaml
f1_dbt:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: ../data/f1.duckdb
```
Probalo con `dbt debug`.

### Paso 2 — Declarar las fuentes (15 min)
En `models/staging/sources.yml`, decile a dbt cuáles son las tablas crudas (`raw.drivers`, `raw.results`, etc.).

### Paso 3 — Capa staging: limpiar (3–4 h)
Un modelo por tabla cruda. **Solo** limpieza, sin lógica de negocio:
- renombrar columnas (`driverId` → `driver_id`)
- convertir tipos (texto → número, texto → fecha)
- unificar valores raros (posición `"R"` = abandono → `NULL` + columna `dnf = true`)

Modelos: `stg_drivers`, `stg_constructors`, `stg_circuits`, `stg_races`, `stg_results`, `stg_qualifying`.

### Paso 4 — Capa marts: el modelo dimensional (4–5 h)
Se organiza en **hechos** (lo que pasó, con números) y **dimensiones** (quién, dónde, cuándo).

```
                 dim_driver
                     │
dim_circuit ── fct_race_results ── dim_constructor
                     │
                 dim_race (temporada, ronda, fecha)
```

**`fct_race_results`**: una fila por piloto por carrera, con:
- `grid_position` (posición de largada)
- `finish_position` (posición final)
- `points`
- `positions_gained` = largada − llegada
- `is_winner`, `is_podium`, `is_dnf`

**Dimensiones:** `dim_driver`, `dim_constructor`, `dim_circuit`, `dim_race`.

### Paso 5 — Marts de análisis (2–3 h)
Algunas tablas con preguntas interesantes, para practicar SQL:
- `mart_teammate_battle`: quién le ganó a su compañero en cada carrera.
- `mart_driver_season`: victorias, podios, puntos y abandonos por piloto y temporada.
- `mart_comebacks`: las mayores remontadas de la historia (más posiciones ganadas).

### Paso 6 — Tests (1–2 h)
En los archivos `.yml` de cada modelo:
- `not_null` y `unique` en las claves
- `relationships`: cada `driver_id` del hecho existe en `dim_driver`
- un test propio: **en una carrera no puede haber dos pilotos con la misma posición final**

```bash
dbt build     # corre los modelos y los tests juntos
```

### Paso 7 — Documentación (30 min)
```bash
dbt docs generate && dbt docs serve
```
Abrí el **gráfico de linaje**: muestra de dónde sale cada tabla. Sacale una captura para el README.

### ✅ Checklist Etapa 2
- [ ] `dbt build` corre sin errores
- [ ] Capa staging con los 6 modelos
- [ ] Hecho + 4 dimensiones
- [ ] Al menos 2 marts de análisis
- [ ] Tests pasando
- [ ] Captura del linaje en el README

**🎓 Qué aprendiste:** dbt (la herramienta más pedida para transformar datos), el modelado dimensional y los tests de calidad de datos.

---

## Etapa 3 — Machine Learning: ¿quién gana la próxima? (1–2 días)

**Objetivo:** estimar la probabilidad de ganar de cada piloto antes de la carrera.

> 💡 **Expectativa realista:** gana uno solo entre ~20 pilotos, así que acertar siempre es imposible. El objetivo es que el modelo **le gane a una regla simple** y que sus probabilidades tengan sentido.

### Paso 1 — Crear la tabla de features en dbt (3–4 h)
Modelo `models/ml/ml_race_features.sql`: **una fila por piloto por carrera**.

| Feature | Qué mide |
|---|---|
| `grid_position` | posición de largada (suele ser la más importante) |
| `avg_finish_last_5` | posición promedio en las últimas 5 carreras |
| `points_last_5` | puntos en las últimas 5 carreras |
| `team_points_last_5` | qué tan bien viene el auto |
| `avg_finish_at_circuit` | historial del piloto en ese circuito |
| `dnf_rate_last_10` | confiabilidad (abandonos recientes) |
| `beat_teammate_rate` | % de veces que le ganó a su compañero |

**Objetivo a predecir (target):** `is_winner` (1 si ganó, 0 si no).

### ⚠️ Paso 2 — Evitar la fuga de datos (*data leakage*)
**Es el error más común.** Cada feature tiene que usar **solo información de carreras anteriores**, nunca de la carrera que querés predecir.

En SQL se resuelve con ventanas que terminan en la fila anterior:
```sql
AVG(finish_position) OVER (
    PARTITION BY driver_id
    ORDER BY race_date
    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING   -- 👈 el "1 PRECEDING" excluye la carrera actual
) AS avg_finish_last_5
```

### Paso 3 — Separar los datos por tiempo (30 min)
**No mezclar al azar.** Se entrena con el pasado y se prueba con el "futuro":

| Conjunto | Temporadas | Para qué |
|---|---|---|
| Entrenamiento | 2014–2023 | el modelo aprende |
| Validación | 2024 | ajustar el modelo |
| Prueba | 2025 | la nota final (se usa una sola vez) |

> Se arranca en 2014 porque los autos y las reglas de antes eran muy distintos.

### Paso 4 — El baseline: la regla a superar (30 min)
Antes de hacer ML: **"gana el que larga primero"**.
Calculá en qué % de las carreras de 2024 pasó eso. Ese es el número a superar.

### Paso 5 — Entrenar (2–3 h)
En `ml/train.py`:
1. Leer `ml_race_features` desde DuckDB con pandas.
2. **Modelo 1:** regresión logística (simple, fácil de entender).
3. **Modelo 2:** LightGBM (más potente).
4. Dentro de cada carrera, el piloto con mayor probabilidad es el "favorito del modelo".

### Paso 6 — Evaluar (1 h)
Compará baseline vs. modelo 1 vs. modelo 2:

| Métrica | Pregunta que responde |
|---|---|
| **Acierto top-1** | ¿en qué % de las carreras ganó el favorito del modelo? |
| **Acierto top-3** | ¿en qué % el ganador real estaba entre los 3 favoritos? |
| **Log loss** | ¿las probabilidades son creíbles? (cuanto más bajo, mejor) |

Mirá también qué features pesaron más (`feature_importances_` en LightGBM).

### Paso 7 — Predecir la próxima carrera (1 h)
En `ml/predict.py`, después de la clasificación del sábado:
1. Correr la ingesta para traer la clasificación.
2. `dbt build` para recalcular las features.
3. Cargar el modelo y mostrar la tabla de probabilidades:

```
Piloto            Prob. de ganar
──────────────────────────────
Piloto A              34%
Piloto B              21%
Piloto C              12%
...
```

### ⚠️ Ojo con 2026
En 2026 cambió el reglamento (autos y motores nuevos), así que lo de años anteriores explica menos lo de ahora. Ideas simples:
- agregar una feature `is_new_regulation_era`, o
- darles más peso a las carreras recientes al entrenar.

Este fenómeno se llama **data drift** (los datos cambian con el tiempo) y es un muy buen tema para mencionar en una entrevista.

### ✅ Checklist Etapa 3
- [ ] `ml_race_features` sin fuga de datos
- [ ] División por temporadas
- [ ] Baseline calculado
- [ ] 2 modelos entrenados y comparados
- [ ] Script de predicción funcionando

**🎓 Qué aprendiste:** cómo los datos bien modelados alimentan un modelo de ML, evitar la fuga de datos, la validación temporal y evaluar contra un baseline.

---

## Cierre: README para el portfolio

El README es lo que va a leer quien mire tu GitHub. Que tenga:
1. **Qué hace** el proyecto (2–3 líneas).
2. **Diagrama** del flujo (el de arriba sirve).
3. **Stack** usado.
4. **Cómo correrlo** (los comandos, en orden).
5. **Resultados:** la tabla baseline vs. modelos y alguna conclusión interesante.
6. **Captura** del linaje de dbt.

---

## Próximos pasos (opcional)
- **Automatizar:** que corra solo cada fin de semana de carrera con Airflow o Prefect.
- **Telemetría:** sumar datos de FastF1 (velocidad, neumáticos) como features.
- **Dashboard:** mostrar las predicciones en Streamlit.
- **Nube:** mover la base a BigQuery o MotherDuck.

---

## Recursos
- API Jolpica-F1: https://github.com/jolpica/jolpica-f1
- Documentación de dbt: https://docs.getdbt.com
- DuckDB: https://duckdb.org/docs
- FastF1: https://docs.fastf1.dev
- Curso gratuito: *Data Engineering Zoomcamp* (DataTalks.Club)
