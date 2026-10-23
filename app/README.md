# Dashboard Streamlit

La app lee exclusivamente las tablas Gold Parquet de REData y AEMET, desde estos objetos de S3:

```text
s3://energy-optimizer-grupo4/outputs/redata/gold_plan_mensual.parquet
s3://energy-optimizer-grupo4/outputs/redata/gold_programacion_horaria.parquet
s3://energy-optimizer-grupo4/outputs/aemet/gold_temperatura_diaria.parquet
```

La región es `eu-north-1`. El bucket, prefijo y región están definidos en [data_loader.py](data_loader.py). No se utilizan CSV locales ni hay una alternativa local si falla S3.

`gold_plan_mensual.parquet` contiene una fila por mes. Sus columnas son `mes`, `precio_spot_medio_mensual_eur_mwh`, `ahorro_estimado_mensual_eur`, `precio_spot_medio_anual_eur_mwh` y `ahorro_estimado_anual_eur`.

`gold_programacion_horaria.parquet` contiene `fecha_local`, `hora_local`, `precio_eur_mwh`, `consumo_baseline_mwh`, `consumo_optimizado_mwh`, `coste_baseline_eur` y `coste_optimizado_eur`. Gold garantiza el orden cronológico de sus filas.

Los antiguos `gold_plan_horario.parquet` y `gold_resumen_diario.parquet` no se leen, aunque sigan en S3: el proceso actual ya no los actualiza. Los totales diarios se obtienen sumando la programación publicada durante la carga cacheada, sin recalcular la optimización.

La tabla AEMET sigue el contrato de [03_gold_aemet.py](../notebooks/03_gold_aemet.py): una fila por `fecha`, con `tmed`, `tmin`, `tmax` y `localidad_tmin`, `provincia_tmin`, `hora_tmin` (y sus equivalentes `_tmax`). Es un resumen **nacional**, no provincial: no permite un selector de provincia. La media diaria es la media de las medias provinciales, con el mismo peso para cada provincia. Los extremos publicados priorizan estaciones con hora disponible y las horas se muestran tal como las entrega AEMET, sin conversión de zona horaria.

## Acceso desde EC2

La conexión usa `boto3` y su cadena estándar de credenciales AWS. En EC2 se recomienda un rol IAM asociado a la instancia mediante un instance profile, sin claves en el código ni en el repositorio.

**Session Manager (SSM) permite acceder a la instancia, pero no concede por sí solo permisos para leer S3.** El rol de la EC2 debe permitir como mínimo:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": [
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/redata/gold_plan_mensual.parquet",
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/redata/gold_programacion_horaria.parquet",
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/aemet/gold_temperatura_diaria.parquet"
      ]
    }
  ]
}
```

No se necesita listar el bucket: se leen los objetos por su clave exacta. Si están cifrados con una clave KMS administrada por el cliente, también se necesita `kms:Decrypt` para esa clave y autorización en su política.

La instancia necesita conectividad con S3, por ejemplo mediante salida HTTPS o un endpoint de VPC para S3. Las políticas del bucket y del endpoint también deben permitir la lectura.

## Carga y actualización

La app descarga los Parquet en memoria y mantiene los resultados validados en caché durante cinco minutos. Cambiar filtros o pantallas no vuelve a descargar los archivos mientras la caché siga vigente.

El botón **Actualizar datos de S3** invalida ambas cachés. REData se vuelve a cargar de inmediato y AEMET al mostrar la programación diaria. La expiración de la caché se comprueba en la siguiente ejecución de la app; no hay sondeo automático.

Los dos archivos deben proceder de la misma ejecución de Gold. Actualiza el dashboard solo cuando haya finalizado la subida de ambos: las dos lecturas de S3 no constituyen una transacción.

No se descargan fuentes de REData, no se recalcula la optimización y no se escribe en S3. Si faltan credenciales, permisos, archivos o coherencia entre las tablas REData, la app muestra el error y detiene la carga. AEMET se carga por separado solo en la programación diaria y mantiene su propia caché de cinco minutos: un error muestra el detalle y el origen S3 dentro del panel de temperatura, sin bloquear los resultados energéticos.

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

## Ejecución posterior en EC2

Las dependencias se declaran en [requirements.txt](../requirements.txt), incluidos `boto3`, `pyarrow` y `streamlit`.

Cuando se autorice la ejecución, desde la raíz del repositorio y con el entorno virtual activado:

```text
python -m pip install -r requirements.txt
python -m streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

No expongas el puerto 8501 a todo Internet. Restringe el acceso al origen autorizado o utiliza un túnel de Session Manager. La URL o el túnel dependerán de la configuración de la EC2.

## Problemas habituales

- **NoCredentialsError**: revisar que la instancia tenga un rol IAM utilizable o credenciales válidas en el entorno. Tener acceso por SSM no garantiza esto.
- **AccessDenied**: revisar `s3:GetObject`, políticas del bucket y del endpoint y, si aplica, permisos de KMS.
- **NoSuchKey o 404**: comprobar los dos nombres y el prefijo `outputs/redata/`.
- **Error de conexión o timeout**: revisar la conectividad de la EC2 con S3 en `eu-north-1`.
- **Faltan columnas o las tablas no coinciden**: utilizar los dos Parquet generados por la misma ejecución del script Gold.
- **Resultados anteriores tras una subida**: pulsar **Actualizar datos de S3** cuando ambos objetos estén subidos.
- **No hay resultados para un trimestre**: los archivos no contienen días válidos de ese trimestre; no significa ahorro cero.
- **Error de horas incompletas o fuera de orden**: revisar que Gold publique el día completo en orden cronológico, conservando las dos horas repetidas de otoño.

## Pruebas

Desde la raíz del repositorio, con el entorno virtual activado:

```text
python -m unittest discover -s app\tests -v
```

Las pruebas generan tablas con las funciones reales de Gold, las serializan en Parquet en memoria y simulan S3. También ejecutan las tres pantallas mediante `streamlit.testing.v1.AppTest`, sin conectarse a AWS ni modificar Gold.
