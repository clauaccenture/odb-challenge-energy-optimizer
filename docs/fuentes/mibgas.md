# MIBGAS

## Papel en el proyecto

MIBGAS es la fuente principal para construir la serie histórica del producto diario D+1. Se utiliza porque permite completar la ventana del modelo hasta septiembre de 2026, mientras que CNMC deja de aportar datos D+1 después de mayo de 2026.

## Acceso

La ingesta utiliza los CSV anuales oficiales del portal de MIBGAS:

```text
https://www.mibgas.es/es/file-access/MIBGAS_Data_{year}.csv?path=AGNO_{year}/XLS
```

La configuración está en `config/mibgas.yml`. El filtro de negocio utilizado es:

- Producto: `GDAES_D+1`.
- Lugar de entrega: `PVB`.
- Área: `ES`.
- Fecha temporal principal: `First Day Delivery`.

Los ficheros originales se conservan en `data/raw/mibgas/`, uno por año.

## Tratamiento de calidad

El notebook `notebooks/02_calidad_mibgas.ipynb`:

1. Lee los CSV separados por `;` y conserva la cabecera real del fichero.
2. Filtra por fecha de entrega, no por día de negociación.
3. Selecciona únicamente `GDAES_D+1`, `PVB` y `ES`.
4. Convierte el precio `MIBGAS Daily Price [EUR/MWh]` a número.
5. Deduplica por fecha de entrega y producto.
6. Escribe la serie y el informe en `data/processed/mibgas/`.

Los outputs principales son:

- `data/processed/mibgas/mibgas_d1.json`
- `data/processed/mibgas/calidad_mibgas.json`

## Cobertura validada

Con los ficheros anuales de 2024, 2025 y 2026 se obtuvieron:

- Ventana: **01/10/2024 - 30/09/2026**.
- Registros finales: **730**.
- Días únicos: **730**.
- Días faltantes: **0**.
- Duplicados eliminados: **46**.

La cobertura alcanza el final de la ventana objetivo del modelo, el **30/09/2026**.

## Decisión frente a CNMC

MIBGAS es la única fuente operativa de producción para D+1. CNMC fue retirada porque representa el mismo ámbito de mercado, pero no entrega exactamente los mismos precios, termina el 31/05/2026 y no completa la ventana del modelo hasta el 30/09/2026. Sus archivos operativos se eliminaron después de conservar el resultado de la comparación y la decisión en [`docs/fuentes/comparacion_cnmc_mibgas.md`](comparacion_cnmc_mibgas.md).

## Ejecución

```text
notebooks/01_ingesta_mibgas.ipynb
notebooks/02_calidad_mibgas.ipynb
```

La ingesta requiere conexión al portal de MIBGAS. Los tests utilizan CSV y respuestas simuladas, sin depender de la red.
