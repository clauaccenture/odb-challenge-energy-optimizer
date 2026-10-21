# Dashboard Streamlit

La app utiliza las tablas finales generadas por `03_gold_redata.py`. Cada compañero puede guardar los CSV en cualquier carpeta de su equipo, sin reproducir la estructura de carpetas de otro compañero.

## Configurar la Ruta de los CSV

1. Coloca los dos archivos finales en una misma carpeta de tu PC, conservando estos nombres exactos:

```text
gold_plan_horario.csv
gold_resumen_diario.csv
```

2. Abre [data_loader.py](data_loader.py) y localiza esta línea al principio del archivo:

```python
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2]
```

3. Sustitúyela por la ruta absoluta de **tu carpeta de CSV**, no por la ruta de un archivo individual. Por ejemplo, si tienes ambos CSV en `D:\Proyecto Energia\resultados_gold`:

```python
DEFAULT_DATA_DIR = Path(r"D:\Proyecto Energia\resultados_gold")
```

El prefijo `r` permite usar las barras de Windows sin escaparlas. Puedes usar espacios en la ruta. Cambia el ejemplo por tu ubicación real; no necesitas mover los CSV junto al código ni usar la ruta de otro compañero. En macOS o Linux, el equivalente sería `Path("/home/usuario/datos/gold")`.

La app buscará ambos nombres dentro de esa carpeta. Los dos CSV deben corresponder a la misma ejecución del proceso Gold. La columna `datetime_utc` no es necesaria: la app utiliza `datetime_local` con su desplazamiento horario.

Si no cambias `DEFAULT_DATA_DIR`, se mantiene el comportamiento original: buscar los CSV en la carpeta superior a `repo_grupo_4`.

No se descargan fuentes, no se recalcula la optimización y no se accede a S3 al abrir la app. Cada recarga vuelve a leer los CSV. Si faltan archivos o no concuerdan las tablas, se muestra un error y se detiene la carga. La app muestra la carpeta de lectura para que puedas comprobar que está apuntando a tu ubicación.

## Pantallas

1. **Resumen ejecutivo**: costes S0/S1, ahorro total y porcentaje ponderado, ahorro mensual, cobertura y selección de una fecha disponible.
2. **Programación diaria**: intervalos locales, precios con cuatro decimales, consumos y costes S0/S1, resumen del día, parámetros del escenario y descarga del plan seleccionado.
3. **Evolución del ahorro**: acumulado, aportación mensual y filtro trimestral. Un trimestre sin registros muestra ausencia de resultados, no ahorro cero.

El filtro de año se obtiene del resumen diario. Solo se agregan días con `estado_optimizacion=optimo`. Los meses sin registros no se inventan y los períodos parciales no se anualizan. El porcentaje agregado es ahorro total / coste S0 total; con coste S0 cero se muestra "No aplica".

## Lectura y Validación

`data_loader.py` comprueba columnas obligatorias, fechas, estados, valores numéricos finitos, horas completas del día local, energía objetivo, límite horario, costes precio por consumo y coherencia entre el plan y el resumen. Los días incompletos o infactibles del resumen se excluyen de los indicadores y del selector de programación.

Las horas se obtienen exclusivamente de `datetime_local`, con sus desplazamientos horarios y conversión a `Europe/Madrid`. La columna temporal redundante puede retirarse del CSV sin afectar a la app. Se conservan los días de 23, 24 y 25 horas; CET/CEST permite distinguir las horas repetidas en otoño.

Los precios proceden de REData a través de las capas Silver/Gold; los consumos representan el escenario industrial del caso 4, no mediciones de una planta. Los costes incluyen energía a precio de mercado, sin peajes, cargos ni impuestos.

Los archivos actuales incluyen el 10 y el 29 de marzo de 2026: 47 horas, coste S0 de 3.661,20 EUR, coste S1 de 2.927,36 EUR y ahorro de 733,84 EUR. Son dos días disponibles dentro de un intervalo de veinte días naturales.

## Ejecución

Necesitas Python 3.10 o superior y la carpeta del proyecto con [streamlit_app.py](streamlit_app.py), [data_loader.py](data_loader.py) y las dependencias declaradas en [pyproject.toml](../pyproject.toml).

En Windows, abre PowerShell en la carpeta `repo_grupo_4`. Si está en otra ubicación, entra primero en ella, sustituyendo la ruta de ejemplo por la tuya:

```powershell
cd "C:\ruta\a\repo_grupo_4"
```

La primera vez, crea un entorno virtual e instala las dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Después de configurar la ruta de los CSV, inicia la app desde esa misma carpeta:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

Abre la URL que muestre la terminal, normalmente `http://localhost:8501`. Si ese puerto está ocupado:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.port 8502
```

Para detener la app, pulsa `Ctrl+C` en la terminal. Para probar otros resultados, sustituye los dos CSV de la carpeta configurada y recarga la app. Si están en otra carpeta, actualiza `DEFAULT_DATA_DIR` y reinicia Streamlit.

## Problemas Habituales

- **No se pudieron cargar las tablas Gold**: comprueba la ruta configurada, los dos nombres exactos y que los archivos estén disponibles localmente, no solo en la nube.
- **Faltan columnas o las tablas no coinciden**: utiliza los dos CSV finales de la misma ejecución, sin cambiar sus cabeceras ni sus valores.
- **No hay resultados para un trimestre**: los archivos no contienen días válidos de ese trimestre; no es un error de conexión ni significa ahorro cero.

El [contrato de datos 1.0](../docs/modelo_datos_y_contrato_streamlit.md) describe una futura integración S3/Parquet. Esta versión utiliza los dos CSV Gold locales y no implementa ese contrato de almacenamiento.