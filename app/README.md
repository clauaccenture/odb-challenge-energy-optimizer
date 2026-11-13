# Dashboard Streamlit

La app lee exclusivamente las tablas Gold Parquet de REData y AEMET, desde estos objetos de S3:

```text
s3://energy-optimizer-grupo4/outputs/redata/gold_plan_mensual.parquet
s3://energy-optimizer-grupo4/outputs/redata/gold_programacion_horaria.parquet
s3://energy-optimizer-grupo4/outputs/aemet/gold_temperatura_diaria.parquet
s3://energy-optimizer-grupo4/outputs/desaladora_som_energia/latest.json
```

La región es `eu-north-1`. El bucket se puede configurar con `S3_BUCKET`
(por defecto `energy-optimizer-grupo4`), y el prefijo del Gold original con
`REDATA_S3_PREFIX`. La carga original está en [data_loader.py](data_loader.py)
y la del caso en [desaladora_data.py](desaladora_data.py). No se utilizan CSV
locales ni hay una alternativa local si falla S3.

## Caso desaladora indexado

El selector **Cálculo del coste** conserva las comparativas anteriores y añade
**Desaladora · Som Energia (simulado)**. Solo este nuevo modo utiliza un plan
reoptimizado por el precio indexado completo. Los otros dos mantienen el plan
optimizado por spot; añadir peajes al coste no equivale a reoptimizar.

El nuevo loader lee `latest.json` una sola vez, después su `metadata.json` y los
tres Parquet bajo `outputs/desaladora_som_energia/runs/<id>/`. Comprueba que las
claves pertenecen a la misma ejecución, sus huellas SHA256 y la del YAML, horas
23/24/25 y desfases UTC, conservación de energía, potencia media, desglose de
precios, costes y coherencia de los agregados. Todo se lee en memoria. Un error
no se sustituye por datos del PC ni por resultados del Gold anterior.

Antes de probar la app, desde la raíz en EC2 con su entorno activado:

```bash
export S3_BUCKET="energy-optimizer-grupo4"
export REDATA_S3_PREFIX="redata"
python notebooks/03_gold_redata.py --config config/config_desaladora.yaml --s3
python -m streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

La app no ejecuta ese cálculo al abrir el túnel. Es una publicación separada del
Gold anterior: volver a ejecutar el comando tras actualizar Silver si se quieren
ver nuevos días. La cuarta pantalla puede consultarse sin que exista el Gold
anterior. Si falta `latest.json`, se muestra el error y el comando de publicación,
manteniendo navegación y botón de actualización para recuperarse.

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
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/aemet/gold_temperatura_diaria.parquet",
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/desaladora_som_energia/*"
      ]
    }
  ]
}
```

No se necesita listar el bucket: se leen los objetos por su clave exacta. Si están cifrados con una clave KMS administrada por el cliente, también se necesita `kms:Decrypt` para esa clave y autorización en su política.

La instancia necesita conectividad con S3, por ejemplo mediante salida HTTPS o un endpoint de VPC para S3. Las políticas del bucket y del endpoint también deben permitir la lectura.

## Carga y actualización

La cobertura procede de los Parquet publicados en S3, no de los datos del PC ni
del tunel SSM. No hay un limite fijo del 31 de octubre: el modo mercado muestra
toda la programacion validada y el modo 6.2TD todos los dias con costes regulados
publicados, incluidos noviembre y diciembre. No se inventan tarifas para anos
sin cobertura regulatoria. Para ver nuevos dias hay que generar y publicar Gold
y actualizar la cache del dashboard; abrir el tunel no ejecuta el pipeline.

La app descarga los Parquet en memoria y mantiene los resultados validados en caché durante cinco minutos. Cambiar filtros o pantallas no vuelve a descargar los archivos mientras la caché siga vigente.

El botón **Actualizar datos de S3** invalida las cachés del Gold original,
del caso desaladora y de AEMET. Se vuelve a leer de inmediato el escenario
seleccionado. AEMET se consulta en la programación diaria; en modo Som, solo
al abrir **Ver temperatura del día**. La expiración de la
caché se comprueba en la siguiente ejecución de la app; no hay sondeo automático.

Los dos archivos deben proceder de la misma ejecución de Gold. Actualiza el dashboard solo cuando haya finalizado la subida de ambos: las dos lecturas de S3 no constituyen una transacción.

No se descargan fuentes de REData, no se recalcula la optimización y no se escribe en S3. Si faltan credenciales, permisos, archivos o coherencia entre las tablas REData, la app muestra el error y detiene la carga. AEMET se carga por separado solo en la programación diaria y mantiene su propia caché de cinco minutos: un error muestra el detalle y el origen S3 dentro del panel de temperatura, sin bloquear los resultados energéticos.

## Pantallas y validaciones

1. **Resumen ejecutivo**: costes S0/S1, ahorro total y porcentaje ponderado, ahorro mensual, cobertura y selección de fecha.
2. **Programación diaria**: intervalos locales, precios, consumos, costes S0/S1 y horas seleccionadas por Gold, junto con sus totales diarios y descarga CSV. Debajo de **Coste del día**, el panel **Temperatura diaria · España** muestra mínima, máxima (con hora, localidad y provincia) y media nacional de la fecha seleccionada. Si falta esa fecha, muestra el día más reciente disponible anterior a ella, con una nota discreta que identifica la fecha real de las temperaturas. Nunca utiliza fechas posteriores a la seleccionada. Si tampoco hay días anteriores, indica la ausencia de datos sin bloquear la programación energética. Los valores u horas nulos se muestran como no disponibles, nunca como cero; no se completan con mediciones de otras fechas. La asignación se muestra tal como viene en el Parquet.
3. **Evolución del ahorro**: acumulado, aportación mensual y filtro trimestral. Un trimestre sin registros muestra ausencia de resultados, no ahorro cero.
4. **Caso desaladora**: siempre consulta la ejecución Som, independientemente
   del selector de coste. Resume la producción y conexión del TFM de referencia,
   separadas de los supuestos eléctricos y contractuales. Presenta la fórmula
   pública Som y una leyenda con el significado de todos sus símbolos, los
   valores de la demo y si son publicados, derivados o supuestos. La cobertura,
   fuentes y peajes por periodo están plegados en **Ver fuentes y cobertura del caso**.
   No se muestran comandos, YAML, JSON, rutas S3, huellas ni metadatos de ejecución.
   Esos datos siguen conservados y verificados internamente, no se eliminan de S3.

En modo Som, las tres primeras pantallas usan los costes de **energía flexible**
publicados, antes de impuestos. La programación diaria destaca únicamente las
horas elegidas y la energía a mover a cada una, ordenadas cronológicamente:
en este caso, **4 horas de 7 MWh y 1 hora de 2 MWh = 30 MWh**. El reparto mostrado
siempre procede del plan Gold: no se fuerza ese patrón ni se recalcula el plan
en Streamlit. Las horas repetidas de otoño conservan su zona y desfase UTC.

Junto a las horas aparece una tarjeta **Coste del día** con coste S0 (antes),
coste S1 (después), ahorro y porcentaje sobre S0. Solo se valora la carga
flexible, no el consumo completo de la planta ni su potencia contratada.
El porcentaje no se calcula si el coste S0 no es positivo.

Debajo queda **Ver desglose de energía flexible**, con los componentes de coste
S0/S1 y su contribución al ahorro. La temperatura también está plegada y no se
consulta hasta abrir su sección. La leyenda y explicación contractual se
reservan para la cuarta pantalla.

El CSV descargado tiene solo siete columnas: **Hora local**, **Precio EUR/MWh**
(indexado completo), **Carga S0 MWh**, **Carga S1 MWh**, **Coste S0 EUR**,
**Coste S1 EUR** y **Ahorro EUR**. Conserva todas las horas del día (23/24/25),
con fecha y desfase UTC, para que las sumas reproduzcan exactamente los costes
y el ahorro de la tarjeta. Las filas con carga S1 mayor que cero son las horas
elegidas. No exporta potencia, consumos o costes de toda la planta ni los
parámetros internos del contrato.

La aproximación horaria (media de cuatro cuartos), los costes comerciales
supuestos y la falta de validación operativa se advierten en todas las vistas Som.
Se conserva el precio indexado negativo como hipótesis, no como condición
contractual confirmada. La configuración no es editable desde el front.
Los días sin datos o incompletos no son seleccionables y no se convierten en
ahorro cero. Un mes sin programación muestra ausencia de datos y se excluye
de la media por mes con datos.

La fecha de programación se selecciona mediante el mismo calendario mensual en el resumen ejecutivo y en la programación diaria. Al pulsar la fecha se abre el calendario; el selector de mes permite recorrer el año elegido en la barra lateral.

Solo están habilitados los días con programación horaria completa y validada. Se deshabilitan tanto los días anteriores o posteriores a la cobertura como los huecos intermedios sin programación publicada. Por ejemplo, con datos hasta el 30 de septiembre de 2026, el 1 de octubre y el 24 de diciembre de 2026 aparecen deshabilitados. El límite se obtiene de Gold, no de la fecha actual del sistema. Al cambiar de año se conserva la fecha si sigue disponible; en caso contrario, se selecciona el primer día válido. El Gold original no publica los días rechazados ni el motivo de exclusión; la app no los inventa. El caso Som sí publica esos estados en su resumen diario.

Se validan columnas obligatorias, meses únicos, fechas, valores numéricos finitos, horas completas y ordenadas, energía diaria de 30 MWh, límite de 7 MWh/h y costes como precio por consumo. Se contrastan ahorros y precios medios mensuales con el horario, y los indicadores anuales con el período completo.

El archivo horario del Gold original no incluye timestamps ni desfases UTC. Para mostrar intervalos inequívocos, se genera el calendario horario de cada fecha en `Europe/Madrid` y se comprueba que su secuencia coincide exactamente con `hora_local`. Las filas se asignan en el orden cronológico garantizado por Gold: en otoño las dos horas 02:00 corresponden primero a CEST y luego a CET. No se ordena por `hora_local`, porque eso podría intercambiar las horas repetidas. El CSV incluye `datetime_local` con su desfase, además de las columnas originales. Si Gold deja de garantizar ese orden, deberá publicar un timestamp con zona horaria.

El ahorro mensual se lee directamente de Gold; no se reconstruye para los gráficos. Los totales diarios, el porcentaje diario y el número de días por mes se agregan desde las horas una sola vez durante la carga cacheada, ya que Gold no los publica en los nuevos archivos.

Los campos llamados anuales representan todo el período cargado, se repiten en cada mes y no están agrupados por año. Con datos de un solo año se utiliza el ahorro anual una sola vez; con varios años se suman los ahorros mensuales del año seleccionado para no mostrar el total global como si fuera anual. Los filtros trimestrales, acumulados y medias mensuales siguen siendo operaciones de presentación.

Los costes S0/S1 del período y el porcentaje ponderado siguen calculándose desde los totales disponibles: Gold no publica esos indicadores agregados. Solo se consideran días con programación completa validada. Los meses sin registros no se inventan y los períodos parciales no se anualizan. El porcentaje agregado es ahorro total / coste S0 total; con coste S0 no positivo se muestra "No aplica".

### Parámetros de las comparativas originales

Los nuevos archivos no publican los parámetros ni la política de negativos. La app identifica los valores mostrados como parámetros del caso 4: 30 MWh diarios, límite de 7 MWh/h, desempate 08:00-17:00 y política de negativos aplicada en Silver. Los objetivos de energía y límite se declaran en el loader y se validan contra el horario. Si cambia el escenario de Gold, deberá actualizarse este contrato o publicarse su metadata.

Los precios proceden de REData; los consumos representan el escenario industrial del caso 4, no mediciones de una planta. En modo solo mercado los costes no incluyen peajes, cargos ni impuestos; el modo 6.2TD añade peajes y cargos. El caso Som utiliza su propia configuración y el precio indexado completo, como se describe arriba.

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
