# Pipeline de datos de Fórmula 1 — temporada 2026

Pipeline ELT de punta a punta: extrae sesiones de F1 con **FastF1**, las guarda crudas en **Parquet**,
las modela con **dbt** sobre **DuckDB** y entrena un modelo que estima la probabilidad de ganar de cada piloto.

Cubre solo la temporada 2026: el cambio de reglamento hace que los años anteriores expliquen poco lo actual.

## Flujo

```
FastF1 ──► data/raw (Parquet) ──► DuckDB ──► dbt (staging → marts) ──► features ──► modelo ML
         └──────── Etapa 1 ────────┘         └──── Etapa 2 ────┘       └────── Etapa 3 ──────┘
```

## Estructura de carpetas

| Carpeta | Qué contiene | Etapa |
|---|---|---|
| `data/raw/` | Datos crudos (*bronze*) tal como llegan de FastF1, en Parquet, particionados por temporada y evento: `data/raw/<tabla>/season=2026/event=<evento>/`. Nunca se modifican. | 1 |
| `data/f1.duckdb` | La base de datos analítica, un solo archivo. | 1–3 |
| `ingestion/` | Scripts de extracción (FastF1 → Parquet) y carga (Parquet → DuckDB). | 1 |
| `f1_dbt/` | Proyecto dbt: *staging* (limpieza), *marts* (modelo dimensional) y features de ML. | 2–3 |
| `ml/` | Entrenamiento del modelo y predicción. | 3 |
| `docs/` | Plan del proyecto y marco teórico. | — |

**Por qué está organizado así:**

- **Una carpeta por etapa:** el repo se lee en el mismo orden en que fluyen los datos.
- **`data/` no está en Git:** se reconstruye corriendo el pipeline. Git guarda el código, no los datos
  (los datos pesan, son binarios y quedarían para siempre en el historial).
- **Crudo separado de limpio:** `data/raw/` es la copia fiel de la fuente. Toda limpieza ocurre después,
  dentro de la base, con dbt. Si una transformación sale mal, se rehace desde lo crudo sin volver a pedir datos.
- **`.gitkeep`:** Git no guarda carpetas vacías, así que las carpetas todavía sin código tienen este archivo vacío.
  Se borra cuando la carpeta recibe su primer archivo real.

## Preparar el entorno

Requiere Python 3.11 o superior (probado con 3.13).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Estado

- [ ] Etapa 0 — Entorno (en curso)
- [ ] Etapa 1 — Ingesta
- [ ] Etapa 2 — Modelado con dbt
- [ ] Etapa 3 — Machine Learning
