# CNMC

## Papel en el proyecto

CNMC se utiliza como fuente alternativa y de contraste para los precios/productos MIBGAS. No es la fuente principal para construir la serie histórica completa del modelo.

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

MIBGAS es la fuente principal para la serie D+1 completa. CNMC queda como fuente secundaria para comparación, control de coherencia y detección de discrepancias durante el periodo solapado.

## Ejecución

```text
notebooks/01_ingesta_cnmc.ipynb
notebooks/02_calidad_cnmc.ipynb
```

La ingesta requiere conexión a la API de CNMC. Los tests utilizan respuestas simuladas y no hacen llamadas externas.
