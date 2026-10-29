# Dashboard Streamlit

La app lee exclusivamente las tablas Gold Parquet de REData y AEMET desde el disco local:

```text
data\outputs\redata\gold_plan_mensual.parquet
data\outputs\redata\gold_programacion_horaria.parquet
data\outputs\aemet\gold_temperatura_diaria.parquet
```

Las rutas están definidas en [data_loader.py](data_loader.py) y se resuelven desde la raíz del repositorio, independientemente de dónde se lance la app. No se utilizan CSV como fuente ni hay conexión a S3, credenciales AWS o datos de ejemplo como alternativa.

`gold_plan_mensual.parquet` contiene una fila por mes. Sus columnas son `mes`, `precio_spot_medio_mensual_eur_mwh`, `ahorro_estimado_mensual_eur`, `precio_spot_medio_anual_eur_mwh` y `ahorro_estimado_anual_eur`.

`gold_programacion_horaria.parquet` contiene `fecha_local`, `hora_local`, `precio_eur_mwh`, `consumo_baseline_mwh`, `consumo_optimizado_mwh`, `coste_baseline_eur` y `coste_optimizado_eur`. Gold garantiza el orden cronológico de sus filas.

Los antiguos `gold_plan_horario.parquet` y `gold_resumen_diario.parquet` no se leen: el proceso actual ya no los actualiza. Los totales diarios se obtienen sumando la programación publicada durante la carga cacheada, sin recalcular la optimización.

La tabla AEMET sigue el contrato de [03_gold_aemet.py](../notebooks/03_gold_aemet.py): una fila por `fecha`, con `tmed`, `tmin`, `tmax` y `localidad_tmin`, `provincia_tmin`, `hora_tmin` (y sus equivalentes `_tmax`). Es un resumen **nacional**, no provincial: no permite un selector de provincia. La media diaria es la media de las medias provinciales, con el mismo peso para cada provincia. Los extremos publicados priorizan estaciones con hora disponible y las horas se muestran tal como las entrega AEMET, sin conversión de zona horaria.

## Arranque local

Desde la raíz del repositorio, instala [las dependencias](../requirements.txt) y configura `AEMET_API_KEY` en `.env` según el [README principal](../README.md). Ejecuta:

```powershell
.\.venv\Scripts\python.exe run_local.py
```

Se descargan los JSON, se generan los Parquet y se abre el servidor local. Visita **http://localhost:8501**. No hacen falta EC2, AWS CLI ni túneles. Si ya hay JSON locales, `run_local.py --skip-download` permite regenerar Gold y arrancar sin acceder a las API.

## Carga y actualización

La app lee los Parquet locales y mantiene los resultados validados en caché durante cinco minutos. Cambiar filtros o pantallas no vuelve a leer los archivos mientras la caché siga vigente.

El botón **Actualizar datos locales** invalida ambas cachés. REData se vuelve a cargar de inmediato y AEMET al mostrar la programación diaria. La expiración de la caché se comprueba en la siguiente ejecución de la app; no hay sondeo automático. El botón no descarga JSON ni ejecuta el pipeline.

Los dos archivos de REData deben proceder de la misma ejecución de Gold. Actualiza el dashboard solo cuando haya finalizado la generación de ambos: las dos lecturas locales no constituyen una transacción.

La app por sí sola no descarga fuentes ni recalcula la optimización. Si faltan permisos de lectura, archivos o coherencia entre las tablas REData, muestra el error y detiene la carga. AEMET se carga por separado solo en la programación diaria y mantiene su propia caché: un error muestra el detalle y la ruta local dentro del panel de temperatura, sin bloquear los resultados energéticos.

El pipeline permite solicitar hasta hoy aunque AEMET todavía no haya publicado todos los días. Recupera los días disponibles y conserva el histórico. Si la primera ingesta no encuentra ninguna temperatura publicada, genera un Parquet AEMET vacío con el contrato completo y un aviso explícito; el panel indica que no hay temperaturas, sin bloquear REData. Una ingesta fallida por red, permisos o datos inválidos no se trata como ausencia de novedades.

## Pantallas y validaciones

1. **Resumen ejecutivo**: costes S0/S1, ahorro total y porcentaje ponderado, ahorro mensual, cobertura y selección de fecha.
2. **Programación diaria**: intervalos locales, precios, consumos, costes S0/S1 y horas seleccionadas por Gold, junto con sus totales diarios y descarga CSV. Debajo de **Coste del día**, el panel **Temperatura diaria · España** muestra mínima, máxima (con hora, localidad y provincia) y media nacional de la fecha seleccionada. Si falta esa fecha, muestra el día más reciente disponible anterior a ella, con una nota discreta que identifica la fecha real de las temperaturas. Nunca utiliza fechas posteriores a la seleccionada. Si tampoco hay días anteriores, indica la ausencia de datos sin bloquear la programación energética. Los valores u horas nulos se muestran como no disponibles, nunca como cero; no se completan con mediciones de otras fechas. La asignación se muestra tal como viene en el Parquet.
3. **Evolución del ahorro**: acumulado, aportación mensual y filtro trimestral. Un trimestre sin registros muestra ausencia de resultados, no ahorro cero.

La fecha de programación se selecciona mediante el mismo calendario mensual en el resumen ejecutivo y en la programación diaria. Al pulsar la fecha se abre el calendario; el selector de mes permite recorrer el año elegido en la barra lateral.

Solo están habilitados los días con programación horaria completa y validada. Se deshabilitan tanto los días anteriores o posteriores a la cobertura como los huecos intermedios sin programación publicada. Por ejemplo, con datos hasta el 30 de septiembre de 2026, el 1 de octubre y el 24 de diciembre de 2026 aparecen deshabilitados. El límite se obtiene de Gold, no de la fecha actual del sistema. Al cambiar de año se conserva la fecha si sigue disponible; en caso contrario, se selecciona el primer día válido. El nuevo Gold no publica los días rechazados ni el motivo de exclusión; la app no los inventa.

Se validan columnas obligatorias, meses únicos, fechas, valores numéricos finitos, horas completas y ordenadas, energía diaria de 30 MWh, límite de 7 MWh/h y costes como precio por consumo. Se contrastan ahorros y precios medios mensuales con el horario, y los indicadores anuales con el período completo.

El archivo no incluye timestamps ni desfases UTC. Para mostrar intervalos inequívocos, se genera el calendario horario de cada fecha en `Europe/Madrid` y se comprueba que su secuencia coincide exactamente con `hora_local`. Las filas se asignan en el orden cronológico garantizado por Gold: en otoño las dos horas 02:00 corresponden primero a CEST y luego a CET. No se ordena por `hora_local`, porque eso podría intercambiar las horas repetidas. El CSV incluye `datetime_local` con su desfase, además de las columnas originales. Si Gold deja de garantizar ese orden, deberá publicar un timestamp con zona horaria.

El ahorro mensual se lee directamente de Gold; no se reconstruye para los gráficos. Los totales diarios, el porcentaje diario y el número de días por mes se agregan desde las horas una sola vez durante la carga cacheada, ya que Gold no los publica en los nuevos archivos.

Los campos llamados anuales representan todo el período cargado, se repiten en cada mes y no están agrupados por año. Con datos de un solo año se utiliza el ahorro anual una sola vez; con varios años se suman los ahorros mensuales del año seleccionado para no mostrar el total global como si fuera anual. Los filtros trimestrales, acumulados y medias mensuales siguen siendo operaciones de presentación.

Los costes S0/S1 del período y el porcentaje ponderado siguen calculándose desde los totales disponibles: Gold no publica esos indicadores agregados. Solo se consideran días con programación completa validada. Los meses sin registros no se inventan y los períodos parciales no se anualizan. El porcentaje agregado es ahorro total / coste S0 total; con coste S0 cero se muestra "No aplica".

### Parámetros del escenario

Los nuevos archivos no publican los parámetros ni la política de negativos. La app identifica los valores mostrados como parámetros del caso 4: 30 MWh diarios, límite de 7 MWh/h, desempate 08:00-17:00 y política de negativos aplicada en Silver. Los objetivos de energía y límite se declaran en el loader y se validan contra el horario. Si cambia el escenario de Gold, deberá actualizarse este contrato o publicarse su metadata.

Los precios proceden de REData; los consumos representan el escenario industrial del caso 4, no mediciones de una planta. Los costes incluyen energía a precio de mercado, sin peajes, cargos ni impuestos.

## Abrir solo el dashboard

Las dependencias se declaran en [requirements.txt](../requirements.txt). El dashboard utiliza `pyarrow` y `streamlit`, sin cliente AWS.

Cuando los Parquet ya estén generados, desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Abre **http://localhost:8501** y conserva la terminal abierta. Detén Streamlit con **Ctrl+C**. La dirección `127.0.0.1` impide exponer el dashboard a otras máquinas.

## Problemas habituales

- **No existe un Parquet**: ejecutar `run_local.py --prepare-only` o, si los JSON ya existen, `run_local.py --skip-download --prepare-only`.
- **Permiso denegado**: revisar los permisos locales de los archivos.
- **Error de descarga**: comprobar Internet y la clave AEMET. Solo el pipeline necesita acceso a las API.
- **Faltan columnas o las tablas no coinciden**: utilizar los dos Parquet generados por la misma ejecución del script Gold.
- **Resultados anteriores tras regenerar Gold**: pulsar **Actualizar datos locales** cuando el pipeline haya terminado.
- **No hay resultados para un trimestre**: los archivos no contienen días válidos de ese trimestre; no significa ahorro cero.
- **Error de horas incompletas o fuera de orden**: revisar que Gold publique el día completo en orden cronológico, conservando las dos horas repetidas de otoño.

## Pruebas

Desde la raíz del repositorio, con el entorno virtual activado:

```text
python -m unittest discover -s app\tests -v
```

Las pruebas generan tablas con las funciones reales de Gold y las guardan como Parquet en carpetas temporales. También ejecutan las tres pantallas mediante `streamlit.testing.v1.AppTest`, sin conectarse a AWS ni modificar los datos del proyecto.
