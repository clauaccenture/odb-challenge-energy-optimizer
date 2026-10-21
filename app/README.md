# Dashboard Streamlit

La app lee exclusivamente las tablas Gold Parquet generadas por [03_gold_redata.py](../notebooks/03_gold_redata.py), desde estos objetos de S3:

```text
s3://energy-optimizer-grupo4/outputs/gold_plan_horario.parquet
s3://energy-optimizer-grupo4/outputs/gold_resumen_diario.parquet
```

La región es `eu-north-1`. El bucket, prefijo y región están definidos en [data_loader.py](data_loader.py). No se utilizan CSV locales ni hay una alternativa local si falla S3. La descarga del plan diario desde el dashboard sigue siendo un CSV.

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
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/gold_plan_horario.parquet",
        "arn:aws:s3:::energy-optimizer-grupo4/outputs/gold_resumen_diario.parquet"
      ]
    }
  ]
}
```

No se necesita listar el bucket: se leen los dos objetos por su clave exacta. Si están cifrados con una clave KMS administrada por el cliente, también se necesita `kms:Decrypt` para esa clave y autorización en su política.

La instancia necesita conectividad con S3, por ejemplo mediante salida HTTPS o un endpoint de VPC para S3. Las políticas del bucket y del endpoint también deben permitir la lectura.

## Carga y actualización

La app descarga los Parquet en memoria y mantiene los resultados validados en caché durante cinco minutos. Cambiar filtros o pantallas no vuelve a descargar los archivos mientras la caché siga vigente.

El botón **Actualizar datos de S3** invalida la caché y vuelve a cargar ambos objetos. La expiración de la caché se comprueba en la siguiente ejecución de la app; no hay sondeo automático.

Los dos archivos deben proceder de la misma ejecución de Gold. Actualiza el dashboard solo cuando haya finalizado la subida de ambos: las dos lecturas de S3 no constituyen una transacción.

No se descargan fuentes de REData, no se recalcula la optimización y no se escribe en S3. Si faltan credenciales, permisos, archivos o coherencia entre las tablas, la app muestra el error y detiene la carga.

## Pantallas y validaciones

1. **Resumen ejecutivo**: costes S0/S1, ahorro total y porcentaje ponderado, ahorro mensual, cobertura y selección de fecha.
2. **Programación diaria**: intervalos locales, precios, consumos y costes S0/S1, parámetros del escenario y descarga del plan seleccionado.
3. **Evolución del ahorro**: acumulado, aportación mensual y filtro trimestral. Un trimestre sin registros muestra ausencia de resultados, no ahorro cero.

La fecha de programación se selecciona mediante el mismo calendario mensual en el resumen ejecutivo y en la programación diaria. Al pulsar la fecha se abre el calendario; el selector de mes permite recorrer el año elegido en la barra lateral.

Solo están habilitados los días presentes en el resumen con `estado_optimizacion=optimo`. Se deshabilitan tanto los días anteriores o posteriores a la cobertura como los huecos intermedios sin programación válida. Por ejemplo, con datos hasta el 30 de septiembre de 2026, el 1 de octubre y el 24 de diciembre de 2026 aparecen deshabilitados. El límite se obtiene de Gold, no de la fecha actual del sistema. Al cambiar de año se conserva la fecha si sigue disponible; en caso contrario, se selecciona el primer día válido.

Se conservan las validaciones de columnas obligatorias, fechas, estados, valores numéricos finitos, horas completas del día local, energía objetivo, límite horario, costes precio por consumo y coherencia entre plan y resumen.

Las horas se obtienen de `datetime_local`, con conversión a `Europe/Madrid`. Se conservan los días de 23, 24 y 25 horas. `fecha_local` procede de la fecha local generada en Gold; no se requiere `datetime_utc`.

Solo se agregan días con `estado_optimizacion=optimo`. Los meses sin registros no se inventan y los períodos parciales no se anualizan. El porcentaje agregado es ahorro total / coste S0 total; con coste S0 cero se muestra "No aplica".

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
- **NoSuchKey o 404**: comprobar los dos nombres y el prefijo `outputs/`.
- **Error de conexión o timeout**: revisar la conectividad de la EC2 con S3 en `eu-north-1`.
- **Faltan columnas o las tablas no coinciden**: utilizar los dos Parquet generados por la misma ejecución del script Gold.
- **Resultados anteriores tras una subida**: pulsar **Actualizar datos de S3** cuando ambos objetos estén subidos.
- **No hay resultados para un trimestre**: los archivos no contienen días válidos de ese trimestre; no significa ahorro cero.
