# Instrucciones de uso y prueba de Streamlit en local

Esta guía corresponde a la rama **`feature_local`**. Todo se ejecuta en el PC: no se utilizan EC2, SSM, túneles ni S3.

## 1. Preparar el entorno

Si recibes la carpeta portable creada con PyInstaller, no necesitas instalar Python ni preparar este entorno. Abre PowerShell en esa carpeta (donde está `EnergyOptimizer.exe`), copia `.env.example` a `.env` si todavía no existe y configura tu clave AEMET. Ejecuta:

```powershell
.\EnergyOptimizer.exe --start 2026-01-01 --end 2026-10-29
```

La app estará en **http://localhost:8501** cuando terminen las descargas y transformaciones. Conserva toda la carpeta, incluida `_internal`; el `.exe` por sí solo no funciona. Los JSON y los Parquet se crean en `data\` junto al ejecutable. La ejecución manual de prueba puede comenzar con un periodo corto:

```powershell
.\EnergyOptimizer.exe --start 2026-10-20 --end 2026-10-22
```

Las instrucciones siguientes son para ejecutar desde el código fuente con Python, no son necesarias para el paquete portable.

En PowerShell, desde la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Si `.env` ya existe, no lo sobrescribas. Configura `AEMET_API_KEY` con tu clave de AEMET OpenData. No compartas la clave ni el archivo. No necesitas variables ni credenciales AWS.

## 2. Descargar, transformar y arrancar

```powershell
.\.venv\Scripts\python.exe run_local.py
```

El comando descarga los JSON de REData y AEMET para el periodo 01/10/2025–30/09/2026, genera Silver y Gold en disco y arranca Streamlit en **http://localhost:8501**.

Para una prueba corta:

```powershell
.\.venv\Scripts\python.exe run_local.py --start 2026-03-10 --end 2026-03-12
```

Los JSON quedan en `data\raw\`, los JSON limpios en `data\processed\` y los Parquet en `data\outputs\`. Los archivos ya descargados se reutilizan. Silver y Gold procesan todo el histórico raw existente: las fechas anteriores limitan la descarga, no filtran archivos previos. Los datos no se suben a Git.

Para descargar desde el 1 de enero de 2026 hasta la fecha actual del PC:

```powershell
.\.venv\Scripts\python.exe run_local.py --start 2026-01-01 --end (Get-Date -Format yyyy-MM-dd)
```

Si faltan días aún no publicados por AEMET, se avisa y se continúa con los disponibles. Un bloque sin datos se consulta día a día; los bloques parciales se conservan y se vuelven a consultar sus días ausentes en futuras ejecuciones. Si no hay temperaturas ni histórico, se generan tablas de temperatura vacías y el dashboard indica la ausencia sin bloquear los resultados REData. Si hay histórico, se conserva y se muestra la última temperatura disponible anterior o igual a la fecha seleccionada, indicando su fecha real.

Los errores reales (red, clave inválida, límites de peticiones o respuestas inválidas) sí detienen el proceso: Streamlit no arranca. Corrige el error y vuelve a ejecutar. Se necesitan precios REData suficientes para generar la programación. La descarga anual puede tardar varios minutos.

## 3. Reutilizar archivos locales

Regenerar los Parquet desde los JSON, sin llamar a las API ni necesitar clave AEMET:

```powershell
.\.venv\Scripts\python.exe run_local.py --skip-download
```

Para preparar los archivos sin arrancar la app, añade `--prepare-only`.

Si los tres Parquet Gold ya existen, puedes abrir únicamente Streamlit:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Mantén la terminal abierta y visita **http://localhost:8501**. Cada persona ejecuta su propia app y utiliza sus propios archivos.

## 4. Comprobar el dashboard

- Funcionan resumen ejecutivo, programación diaria y evolución del ahorro.
- Se indica **Gold local** y la carpeta de los Parquet locales.
- Seleccionar un día cambia la programación y permite descargar el CSV.
- La fecha se conserva al pasar del resumen a la programación diaria.
- El calendario solo habilita días con programación completa validada.
- El panel de temperatura utiliza AEMET local y conserva los valores nulos.
- Un error de AEMET no bloquea los resultados energéticos.
- Si faltan los Parquet REData, se muestra un error que indica cómo generarlos, sin consultar S3 ni inventar resultados.

La cobertura depende de los JSON descargados. Para el histórico completo del caso hay 365 días y 8.760 horas; no son los recuentos esperados de una prueba de tres días.

Después de regenerar Gold, pulsa **Actualizar datos locales**. Este botón limpia la caché de cinco minutos y relee los archivos; no descarga datos ni ejecuta el pipeline. Espera a que termine Gold antes de actualizar.

## 5. Pruebas automáticas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s notebooks\tests -v
.\.venv\Scripts\python.exe -m unittest discover -s app\tests -v
```

Se usan respuestas simuladas de API y Parquet temporales. No se necesitan credenciales ni se modifica el histórico local.

## 6. Al terminar

Detén Streamlit con **Ctrl+C** en la terminal que lo arrancó. Los JSON y los Parquet permanecen en el PC para la siguiente ejecución.
