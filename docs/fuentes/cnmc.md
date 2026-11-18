# CNMC

## Papel en el proyecto

CNMC queda retirada del pipeline operativo. Se conserva únicamente como histórico de auditoría, porque publica el mismo ámbito de mercado y producto D+1 que MIBGAS, pero con precios no idénticos y cobertura incompleta de la ventana del modelo.

## Acceso

La ingesta utiliza el endpoint CKAN `datastore_search`:

```text
https://catalogodatos.cnmc.es/api/3/action/datastore_search
```

La configuración está en `config/cnmc.yml`. Se definen dos recursos:

- `indice_mibgas`: índice MIBGAS.
- `producto_diario_d1`: producto diario D+1, filtrado por `Producto diario D+1`.

La descarga se realiza por páginas mediante `limit` y `offset`. Las respuestas originales se conservan en `data/raw/cnmc/`.

## Tratamiento de calidad

El notebook `notebooks/02_calidad_cnmc.ipynb`:

1. Clasifica los ficheros raw como válidos, vacíos, malformados o ilegibles.
2. Filtra la ventana temporal usando la fecha de negociación.
3. Filtra el producto D+1 cuando aplica.
4. Normaliza el precio a EUR/MWh.
5. Deduplica por fecha de negociación, producto y recurso.
6. Escribe la serie procesada y el informe en `data/processed/cnmc/`.

## Limitación de cobertura

La comprobación realizada sobre el producto diario D+1 muestra que CNMC tiene registros hasta el **31/05/2026**. No hay datos posteriores suficientes para completar la ventana objetivo del proyecto, que llega hasta el **30/09/2026**.

Por tanto:

- CNMC no debe utilizarse como única fuente para entrenar o validar la ventana completa.
- Los meses de junio a septiembre de 2026 quedarían sin cobertura CNMC.
- La ausencia de registros posteriores no debe interpretarse como precios cero ni como días sin precio.
- CNMC se mantiene como fuente de contraste para el periodo que sí cubre.

## Decisión del proyecto

Se decidió retirar CNMC de la construcción de la serie productiva. MIBGAS es la única fuente operativa para D+1 porque cubre la ventana completa y evita mantener dos ingestas con distinta cobertura y discrepancias de precio sin un uso productivo definido.

Los raw, processed, configuración, notebooks y tests de CNMC se mantienen como registro histórico reproducible de la decisión y del periodo solapado. No deben incorporarse nuevos datos CNMC ni mezclarse sus resultados con la serie productiva salvo que se reabra explícitamente esta decisión.

La comparación reproducible y sus resultados están documentados en [`docs/fuentes/comparacion_cnmc_mibgas.md`](comparacion_cnmc_mibgas.md).

## Ejecución

```text
notebooks/01_ingesta_cnmc.ipynb
notebooks/02_calidad_cnmc.ipynb
```

La ingesta requiere conexión a la API de CNMC. Los tests utilizan respuestas simuladas y no hacen llamadas externas.
