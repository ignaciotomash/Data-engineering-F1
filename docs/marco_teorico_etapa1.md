# 📚 Marco teórico — Etapa 1: Ingesta

Este documento acompaña al plan del proyecto. Explica **qué está pasando y por qué** en cada paso de la Etapa 1. Al final hay un glosario de ingeniería de datos y ML.

---

## 1. ¿Qué hace un ingeniero de datos?

Un ingeniero de datos construye el **camino que recorren los datos**: desde donde se generan hasta donde alguien los usa (un analista, un dashboard, un modelo de ML).

A ese camino se le llama **pipeline** (tubería), y casi siempre tiene tres momentos:

```
  FUENTE            →        ALMACENAMIENTO        →        CONSUMO
(API, app, archivo)       (base de datos, data lake)    (análisis, dashboards, ML)
```

En la Etapa 1 hacemos la primera mitad: **sacar los datos de la fuente y guardarlos**. A esto se le llama **ingesta**.

---

## 2. ETL vs. ELT: el orden importa

Hay dos formas clásicas de armar un pipeline:

| | ETL | ELT |
|---|---|---|
| Orden | **E**xtraer → **T**ransformar → **C**argar | **E**xtraer → **C**argar → **T**ransformar |
| Dónde se transforma | antes de guardar, en el código | después de guardar, dentro de la base (con SQL) |
| Cuándo se usaba / usa | era el estándar cuando el almacenamiento era caro | es el estándar actual, con bases analíticas rápidas y baratas |

**En este proyecto hacemos ELT:**
- **E** → el extractor pide los datos a la API (Etapa 1)
- **L** → guardamos el JSON crudo y lo cargamos en DuckDB (Etapa 1)
- **T** → dbt limpia y modela con SQL (Etapa 2)

**Ventaja de ELT:** como guardás todo crudo primero, si te equivocás al transformar, volvés a transformar sin tener que pedir los datos de nuevo.

---

## 3. La fuente: cómo funciona una API

### ¿Qué es una API REST?
Es una "puerta" que ofrece un servicio para que otros programas le pidan datos. Le hacés un **pedido HTTP** a una URL (un **endpoint**) y te devuelve una **respuesta**, normalmente en **JSON**.

```
Tu script  ──── GET /ergast/f1/2024/results.json ────►  Servidor Jolpica
           ◄─── 200 OK + JSON con los resultados ─────
```

### Códigos de respuesta que te vas a cruzar
| Código | Significa | Qué hacer |
|---|---|---|
| `200` | Todo bien | Procesar la respuesta |
| `404` | No existe ese recurso | Revisar la URL |
| `429` | Demasiados pedidos | Esperar y reintentar más despacio |
| `500`–`503` | Error del servidor | Reintentar más tarde |

### Paginación
Las APIs no devuelven millones de registros de una vez: los entregan **por páginas**.
- `limit` = cuántos registros por página
- `offset` = desde qué registro empezar
- `total` = cuántos hay en total

Si hay 2.500 resultados y el límite es 100, necesitás 25 pedidos (offset 0, 100, 200… 2.400).

### Límites de uso (*rate limiting*) y reintentos
Las APIs gratuitas limitan cuántos pedidos podés hacer por segundo u hora para no saturarse. Por eso:
- **Pausa entre pedidos** (`time.sleep`) → ser un buen "vecino".
- **Reintentos con espera creciente** (*exponential backoff*): si falla, esperás 1 s, luego 2 s, luego 4 s… La red falla a veces; un buen pipeline lo asume y no se cae por un error pasajero.
- **Timeout**: si el servidor no responde en X segundos, cortás. Así el script nunca queda colgado para siempre.

---

## 4. La capa cruda (*raw*): no tocar

Lo primero que hacemos con los datos es **guardarlos exactamente como llegaron**. Esta zona se llama **raw**, **landing** o **bronze**.

**¿Por qué no limpiarlos directamente?**
1. **Reproducibilidad:** si mañana cambiás la lógica de limpieza, la volvés a aplicar sobre lo crudo.
2. **Auditoría:** si un número se ve raro, podés revisar qué mandó realmente la fuente.
3. **Independencia de la fuente:** la API puede cambiar, caerse o desaparecer (le pasó a Ergast). Lo que guardaste sigue estando.

Esta idea de capas es la **arquitectura medallion**:

```
🥉 Bronze (raw)      →   🥈 Silver (staging)     →   🥇 Gold (marts)
datos tal cual llegan    limpios y con tipos          listos para analizar
     Etapa 1                  Etapa 2                     Etapa 2
```

### Particionar los archivos
Guardar un archivo por temporada (`season=2024.json`) es una forma simple de **partición**: dividir los datos en partes según una columna. Así podés volver a bajar solo una temporada sin tocar el resto.

---

## 5. De JSON anidado a tablas

### El problema
La API devuelve datos **anidados** (estructuras dentro de estructuras):

```json
{ "raceName": "Italian GP",
  "Results": [
    { "position": "1", "Driver": { "driverId": "leclerc" }, "points": "25" },
    { "position": "2", "Driver": { "driverId": "piastri" }, "points": "18" }
  ] }
```

Una base de datos, en cambio, trabaja con **tablas**: filas y columnas, sin anidamiento.

### La solución: aplanar
Convertimos cada elemento de la lista en una fila, repitiendo los datos del "padre":

| race_name | position | driver_id | points |
|---|---|---|---|
| Italian GP | 1 | leclerc | 25 |
| Italian GP | 2 | piastri | 18 |

En pandas esto se hace con `pd.json_normalize()`.

### Normalización: no repetir información
En lugar de guardar el nombre, la nacionalidad y la fecha de nacimiento del piloto en cada resultado, los guardamos **una sola vez** en `drivers` y en `results` solo ponemos el `driver_id`. Por eso tenemos 6 tablas separadas y no una gigante. Así, si un dato cambia, se corrige en un solo lugar.

### Claves
- **Clave primaria (PK):** identifica cada fila de forma única. En `drivers` es `driver_id`; en `results` es la combinación `season + round + driver_id`.
- **Clave foránea (FK):** una columna que apunta a la clave primaria de otra tabla (`results.driver_id` → `drivers.driver_id`). Es lo que permite unir tablas con `JOIN`.

### Granularidad (*grain*)
Es la pregunta **"¿qué representa una fila?"**. Hay que definirla siempre antes de crear una tabla. En `results`, una fila = un piloto en una carrera. Si no tenés claro el grain, aparecen duplicados y los números se inflan.

---

## 6. ¿Dónde guardamos? OLTP vs. OLAP

Hay dos grandes familias de bases de datos:

| | OLTP (transaccional) | OLAP (analítica) |
|---|---|---|
| Ejemplos | PostgreSQL, MySQL | DuckDB, BigQuery, Snowflake |
| Pensada para | muchas operaciones chicas (una compra, un login) | pocas consultas que recorren millones de filas |
| Guarda los datos | por **fila** | por **columna** |
| Uso típico | el backend de una app | análisis, reportes, ML |

Elegimos **DuckDB** porque es OLAP, **columnar** y vive en un solo archivo, sin servidor.

**¿Por qué columnar es más rápido para analizar?** Si preguntás "¿promedio de puntos?", una base columnar lee **solo** la columna `points`. Una base por filas tiene que leer cada fila entera.

---

## 7. Idempotencia y tipos de carga

### Idempotencia
Un proceso es **idempotente** si correrlo una vez o diez veces deja **el mismo resultado**. Es uno de los principios más importantes de la ingeniería de datos, porque los pipelines **se re-ejecutan** constantemente: por errores, por reintentos, por correcciones.

❌ **No idempotente:** `INSERT` a secas → cada ejecución duplica las filas.
✅ **Idempotente:** borrar la temporada y volver a insertarla (*delete + insert*), o insertar solo si no existe (*upsert*).

### Tipos de carga
| Tipo | Qué hace | Cuándo |
|---|---|---|
| **Completa** (*full load*) | Borra todo y carga todo de nuevo | Datos chicos, o la primera vez |
| **Incremental** | Solo trae lo nuevo desde la última carga | Datos grandes o que se actualizan seguido |

En la Etapa 1 usamos una mezcla: las temporadas cerradas se bajan **una vez** y la temporada actual se **recarga** cada vez, porque sigue cambiando.

---

## 8. Verificar: calidad de datos básica

Que el script termine sin errores **no significa** que los datos estén bien. Por eso al final hacemos chequeos simples:

| Dimensión | Pregunta | Ejemplo en F1 |
|---|---|---|
| **Completitud** | ¿Falta algo? | ¿Hay carreras sin resultados? |
| **Unicidad** | ¿Hay duplicados? | ¿Un piloto aparece dos veces en la misma carrera? |
| **Validez** | ¿Los valores tienen sentido? | ¿Hay puntos negativos? |
| **Consistencia** | ¿Coincide con la realidad? | ¿El que más victorias tiene es quien esperás? |

En la Etapa 2 estos chequeos se automatizan con los **tests de dbt**.

---

## 🗺️ Resumen visual de la Etapa 1

```
┌────────────┐  pedidos HTTP   ┌─────────────┐   guardar tal cual   ┌──────────────┐
│ API Jolpica │ ─────────────► │ extract.py  │ ──────────────────► │ data/raw/    │
│  (fuente)   │  paginación,   │             │                      │ JSON (bronze)│
└────────────┘  pausas,        └─────────────┘                      └──────┬───────┘
                reintentos                                                  │ aplanar
                                                                            ▼ (pandas)
                                                            ┌──────────────────────────┐
                                                            │ DuckDB · esquema raw     │
                                                            │ 6 tablas con PK/FK       │
                                                            │ carga idempotente        │
                                                            └────────────┬─────────────┘
                                                                         ▼
                                                              chequeos de calidad (SQL)
```

---

# 📖 Glosario

## Ingeniería de datos

| Término | Definición simple |
|---|---|
| **API** | Interfaz que permite a un programa pedirle datos o acciones a otro. |
| **Arquitectura medallion** | Organizar los datos en capas: bronze (crudo), silver (limpio), gold (listo para usar). |
| **Backfill** | Cargar o reprocesar datos de fechas pasadas. |
| **Backoff exponencial** | Estrategia de reintento: esperar cada vez más tiempo entre intentos (1 s, 2 s, 4 s…). |
| **Base columnar** | Base que guarda los datos por columna; muy rápida para análisis. |
| **Calidad de datos** | Qué tan completos, únicos, válidos y consistentes son los datos. |
| **Clave foránea (FK)** | Columna que apunta a la clave primaria de otra tabla. |
| **Clave primaria (PK)** | Columna (o combinación) que identifica cada fila de forma única. |
| **DAG** | "Grafo dirigido acíclico": la forma de describir tareas y sus dependencias en un orquestador. |
| **Data lake** | Almacenamiento de archivos (JSON, CSV, Parquet) en bruto, barato y flexible. |
| **Data warehouse** | Base analítica con datos limpios y estructurados para consultar con SQL. |
| **dbt** | Herramienta para transformar datos con SQL, con tests, documentación y linaje. |
| **Dimensión** | Tabla que describe el "quién, dónde, cuándo" (pilotos, circuitos, fechas). |
| **ELT / ETL** | Extraer-Cargar-Transformar / Extraer-Transformar-Cargar: el orden de un pipeline. |
| **Endpoint** | Una URL específica de una API que devuelve un tipo de dato. |
| **Esquema (schema)** | Estructura de una tabla (columnas y tipos), o grupo de tablas dentro de una base. |
| **Granularidad (grain)** | Lo que representa una fila de una tabla. |
| **Hecho (fact)** | Tabla con los eventos medibles (resultados, ventas), con números para sumar o promediar. |
| **Idempotencia** | Propiedad de un proceso que da el mismo resultado sin importar cuántas veces se corra. |
| **Ingesta** | Traer datos desde una fuente hacia tu almacenamiento. |
| **JSON** | Formato de texto para datos estructurados, común en APIs. Puede estar anidado. |
| **Linaje (lineage)** | El "árbol genealógico" de una tabla: de qué fuentes y transformaciones sale. |
| **Carga incremental** | Traer solo los datos nuevos o modificados desde la última ejecución. |
| **Mart** | Tabla final orientada a responder preguntas concretas del negocio. |
| **Modelo dimensional** | Diseñar tablas en hechos + dimensiones (esquema estrella). |
| **Normalización** | Separar datos en tablas para no repetir información. |
| **OLTP / OLAP** | Bases transaccionales (muchas operaciones chicas) / analíticas (consultas grandes). |
| **Orquestación** | Programar y coordinar cuándo y en qué orden corren las tareas (Airflow, Prefect). |
| **Paginación** | Entregar resultados por partes (páginas) en vez de todos juntos. |
| **Parquet** | Formato de archivo columnar y comprimido, estándar en data lakes. |
| **Partición** | Dividir los datos en partes según una columna (ej: por temporada) para leerlos más rápido. |
| **Pipeline** | Cadena de pasos que mueve y transforma datos desde la fuente hasta su uso. |
| **Rate limit** | Límite de pedidos que una API acepta en un período de tiempo. |
| **Raw / bronze** | Capa donde se guardan los datos exactamente como llegaron. |
| **Staging / silver** | Capa donde los datos se limpian, se renombran y se tipan. |
| **Timeout** | Tiempo máximo de espera de una respuesta antes de abortar. |
| **Upsert** | Insertar una fila si no existe, o actualizarla si ya existe. |
| **Watermark** | Marca del último dato procesado; se usa para cargas incrementales. |

## Machine Learning

| Término | Definición simple |
|---|---|
| **Baseline** | Regla simple que el modelo debe superar para que valga la pena (ej: "gana el que larga primero"). |
| **Clasificación** | Tipo de problema de ML donde se predice una categoría (ganó / no ganó). |
| **Conjunto de entrenamiento / validación / prueba** | Datos para que el modelo aprenda / para ajustarlo / para evaluarlo al final. |
| **Data drift** | Cuando los datos cambian con el tiempo y el modelo pierde precisión (ej: nuevo reglamento). |
| **Data leakage (fuga de datos)** | Usar sin querer información del futuro para predecir; da resultados falsamente buenos. |
| **Desbalance de clases** | Cuando una clase es mucho más rara que otra (1 ganador vs. ~19 que no ganan). |
| **Feature (variable)** | Dato de entrada que el modelo usa para predecir (ej: posición de largada). |
| **Feature engineering** | Crear features útiles a partir de los datos crudos. |
| **Feature importance** | Cuánto influyó cada feature en las predicciones del modelo. |
| **Gradient boosting** | Familia de modelos (LightGBM, XGBoost) que combina muchos árboles de decisión. Muy usada con datos tabulares. |
| **Log loss** | Métrica que evalúa qué tan buenas son las probabilidades predichas (más bajo = mejor). |
| **Overfitting (sobreajuste)** | Cuando el modelo "memoriza" el entrenamiento y falla con datos nuevos. |
| **Probabilidad calibrada** | Cuando un 30 % predicho realmente ocurre ~30 % de las veces. |
| **Regresión logística** | Modelo simple de clasificación que devuelve probabilidades; ideal para empezar. |
| **Target (objetivo)** | Lo que se quiere predecir (ej: `is_winner`). |
| **Validación temporal** | Separar los datos por fecha (entrenar con el pasado, probar con el futuro) en vez de al azar. |
