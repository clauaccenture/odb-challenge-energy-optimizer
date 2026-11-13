# Energy Optimizer – AS-IS (punto de partida)

*Documento que escribe el punto del que partimos: la primera versión del proyecto, tal y como se entregó y está documentada en el `README.md` raíz, cuando **todavía no teníamos un caso concreto** sobre el que definir restricciones. Las mejoras y cambios posteriores (caso de la desaladora, contrato con Som Energia, restricciones operativas, etc.) están en el documento **TO-BE** (`TO-BE.md`).*

## 1. Qué es el proyecto

**Energy Optimizer** analiza cómo reducir el coste de la carga eléctrica flexible de una planta industrial desplazando el consumo hacia las horas de menor precio del mercado diario, **sin reducir la energía consumida**. Lema: *no consumas menos, consume en el momento adecuado.*

**Pregunta de negocio:** ¿cuánto puede ahorrar la planta en un año consumiendo su carga flexible en las horas de menor precio del mercado diario?

**Periodo analizado:** 01/10/2025 – 30/09/2026 (365 días).

## 2. Punto de partida: planteamiento y supuestos

La primera versión trabaja con una planta industrial **genérica**, definida por una ficha del caso, sin restricciones operativas propias de ninguna instalación real.

| Supuesto | Valor | Impacto si no se cumple |
|---|---|---|
| Compra de electricidad | Indexada al precio del mercado diario | Cambiaría el modelo de coste |
| Consumo flexible diario | 30 MWh/día, desplazable dentro del mismo día | El ahorro variaría proporcionalmente |
| Potencia máxima flexible | 7 MWh por hora | Cambiaría la programación óptima |
| Operación actual (S0) | 2,5 MWh/h entre las 08:00 y las 20:00 | Cambiaría el baseline de comparación |
| Programación posterior a la casación | Sí (el precio del día siguiente ya es conocido) | Haría falta una previsión de precios |
| Precios negativos | Se sustituyen por 0 para el cálculo | Modificaría parcialmente los costes |

**Hipótesis del equipo**

1. Es posible ahorrar sin consumir menos: desplazar la misma energía hacia horas más baratas reduce el coste.
2. El ahorro varía entre días: hay variabilidad diaria e intradiaria de precios.
3. Las horas más baratas no son necesariamente nocturnas: la ventana óptima se determina cada día.
4. El mix de generación (especialmente la solar) influye en el patrón de precios.

## 3. Fuentes de datos

| Fuente | Datos utilizados | Acceso |
|---|---|---|
| **REData (Red Eléctrica)** | Hora y precio del mercado diario | API REST JSON sin token |
| **AEMET OpenData** | Fecha, provincia, temperatura máxima, mínima y media, hora de máxima y mínima | API REST con clave gratuita (`AEMET_API_KEY`) |

## 4. Calidad de datos y decisiones de tratamiento

| Fuente | Registros | % nulos en campos clave | Duplicados | % cruce |
|---|---:|---|---:|---:|
| REData | 35.040 cuartos de hora | 0 % | 0 | 100 % |
| AEMET | 305.398 (299.073 tras limpieza) | tmax 0,04 %; tmin 0,09 %; tmed 0,13 % | 0 | 100 % |

**REData**

- **Resolución:** el mercado opera en periodos de 15 minutos; se pasa a hora con la media de los cuatro valores.
- **Precios negativos:** decisión del equipo, se sustituyen por 0 en el cálculo y se conserva el original en Bronze.
- **Horas incompletas:** se avisa si una hora no tiene sus cuatro cuartos; en el periodo no hay ninguna. Gold omite los días que no tengan 23, 24 o 25 horas.
- **Cambios de hora:** los días con 23 o 25 horas (29/03/2026 y 26/10/2025) se tratan sin asumir 24.

**AEMET**

- **Decimales:** la API devuelve coma decimal; se sustituye por punto.
- **Nulos:** se eliminan las filas sin ninguna temperatura (2,07 %). Las horas no válidas quedan nulas, nunca 0.
- **Descarga:** la API limita a tramos de 15 días; el script divide el periodo y se ejecuta con un solo comando.
- **Silver:** un registro por estación y día, sin agregar. La temperatura media de España y los extremos se calculan en Gold.

**Cruce entre fuentes:** la clave es la fecha. Ambas cubren los 365 días, por lo que no se excluye ninguno.

## 5. Solución: cómo se calcula el ahorro

Se compara cada día, durante un año completo, la operación actual (S0) con la optimizada (S1). Misma energía, mismo límite por hora; solo cambia **cuándo** se consume.

- **S0 (baseline):** 30 MWh/día repartidos entre las 08:00 y las 20:00, a 2,5 MWh/h.
- **S1 (optimizado):** los mismos 30 MWh/día, asignados a las horas de menor precio con un máximo de 7 MWh por hora.

**Algoritmo diario (greedy)**

1. Obtener los precios horarios del mercado diario.
2. Ordenar las horas de menor a mayor precio.
3. Asignar `min(7, energía restante)` empezando por las más baratas (7 + 7 + 7 + 7 + 2).
4. Calcular el coste diario de S0 y S1.
5. Ahorro diario = coste S0 − coste S1. Ahorro anual = suma de los 365 días.

**Decisiones metodológicas**

- Comparación día a día sobre un año completo; no se extrapola un día al resto.
- S1 usa los precios conocidos del mercado diario. La previsión de precios no forma parte del núcleo.
- **Desempate:** con precios iguales se prioriza la franja diurna 08:00–17:00 y, si persiste, la hora más temprana.

## 6. Resultados

| Métrica | Baseline S0 | Modelo S1 | Mejora |
|---|---:|---:|---:|
| Coste anual | 520.345,63 € | 234.659,08 € | 285.686,55 € |
| Ahorro relativo | – | – | 54,90 % |

**Recomendación del proyecto:** programar la carga flexible cada día, una vez publicados los precios del mercado diario, asignándola a las horas de menor coste dentro de las restricciones definidas.

El análisis complementario de temperatura y precio (script 04) es solo descriptivo: la temperatura va muy ligada a la estación y otras variables también mueven el precio, así que no implica causalidad.

## 7. Arquitectura y pipeline

Datos en tres capas: **Bronze** (raw, sin modificar), **Silver** (limpio) y **Gold** (resultados). Cada script guarda en local (`data/`, no versionada) y, si `S3_BUCKET` está definido, también en S3 (`raw/`, `processed/`, `outputs/`).

| Paso | Script (`notebooks/`) | Qué hace | Resultado |
|---|---|---|---|
| 1 | `01_ingesta_redata.py` | Descarga los precios (un JSON por día, reanudable) | `raw/redata/` (365 ficheros) |
| 2 | `01_ingesta_aemet.py` | Descarga temperaturas en tramos de 15 días | `raw/aemet/` (25 ficheros) |
| 3 | `02_calidad_redata.py` | Limpia y pasa a resolución horaria | `processed/redata/` |
| 4 | `02_calidad_aemet.py` | Limpia las temperaturas | `processed/aemet/` |
| 5 | `03_gold_redata.py` | Calcula S0, S1 y el ahorro | `gold_plan_mensual.parquet`, `gold_programacion_horaria.parquet` |
| 6 | `03_gold_aemet.py` | Resume la temperatura nacional por día | `gold_temperatura_diaria.parquet` |
| 7 | `04_analisis_temperatura_precio.py` | Cruza temperatura y precio | Parquet y gráfico |

Los scripts deben ejecutarse **en este orden**, desde la raíz del repo y con el entorno activado. Valores de control esperados: 365 ficheros de REData, 25 de AEMET, `rows_read` 35040, `hours_output` 8760 y `Ahorro total: 285686.55 EUR | ahorro ponderado: 54.90 %`.

## 8. Dashboard (Streamlit)

- Capa de visualización **opcional**: no es necesaria para ejecutar el pipeline.
- Lee las tablas Gold publicadas en S3 (el bucket está definido en `app/data_loader.py`; si se usa otro, hay que editarlo ahí).
- Los costes mostrados incluyen la energía a precio de mercado, sin peajes, cargos ni impuestos.
- Documentación en `app/README.md` y guía de acceso en `app/instrucciones uso prueba streamlit.md`.

## 9. Infraestructura y ejecución

- **AWS, región `eu-north-1` (Estocolmo):** una instancia EC2 con rol IAM (sin claves en el repositorio) y un bucket S3.
- **Acceso:** consola AWS → EC2 → Session Manager. Para ver el dashboard, túnel SSM desde el PC y acceso a `http://localhost:18501`.
- **Entorno:** Python 3.11 (en Amazon Linux 2023 `python3` es 3.9 y no vale), `pip install -r requirements.txt`.
- **Variables (`.env`, no versionado):** `AEMET_API_KEY`, `S3_BUCKET`, `AWS_DEFAULT_REGION`. Plantilla en `.env.example`.
- **Solo en local:** dejar `S3_BUCKET` vacío y añadir `--no-s3` a los scripts.
- **Instrucciones completas paso a paso:** `README.md` raíz, sección 8.

## 10. Limitaciones conocidas

- Se usa el precio del mercado diario, que **no es el coste final de la factura eléctrica**.
- Solo se modela la carga flexible del caso; **no hay restricciones operativas** de una planta real.
- El único criterio de optimización es el coste económico (no emisiones ni sostenibilidad).
- Una hora sin sus cuatro cuartos de hora queda excluida de la asignación de S1.
- Los precios negativos se sustituyen por 0; con precios negativos reales el ahorro sería mayor (decisión conservadora).
- Los resultados dependen de la calidad y disponibilidad de los datos abiertos.
- No hay previsión de precios: S1 asume que el precio del día siguiente ya se conoce.

## 11. Arranque rápido para alguien nuevo

1. Leer este documento y después el TO-BE.
2. Pedir acceso corporativo a AWS (EC2 por SSM y permisos sobre S3) y una clave gratuita de AEMET OpenData.
3. Clonar el repo, crear el entorno con Python 3.11, instalar dependencias y copiar `.env.example` a `.env`.
4. Ejecutar el pipeline en orden (README raíz, sección 8.6) o consultar los resultados ya publicados en el dashboard.

> **Nota:** el código de la rama `develop` ya incluye cambios posteriores a este punto de partida. Están descritos en el TO-BE.
