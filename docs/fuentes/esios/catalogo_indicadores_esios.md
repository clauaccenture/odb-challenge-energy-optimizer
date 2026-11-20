# Catálogo de indicadores ESIOS

Snapshot obtenido el 2026-11-12 (1982 indicadores).

El [CSV completo](./catalogo_indicadores_esios.csv) incluye el ID, nombre, nombre corto, descripción y publicación indicada por ESIOS. La descripción se ha limpiado de etiquetas HTML; la publicación es una columna separada para facilitar la lectura y el filtrado. Estos metadatos no validan por sí solos la cobertura ni la idoneidad de cada indicador.

Fuente: [API ESIOS](https://api.esios.ree.es/indicators).

## Indicadores descartados por cobertura

Los indicadores `31` (Generación programada PBF Importación Andorra) y `628` (Precio Reserva de potencia adicional a subir) se retiraron de la ingesta operativa tras ejecutar la validación sobre la ventana del modelo (`2024-10-01` a `2026-09-30`). Cada uno presentó 29 bloques vacíos, 0 bloques válidos, 0 bloques malformados y 0 bloques ilegibles. Al no existir ninguna observación utilizable, no pueden aportar variables al modelo y mantenerlos solo añade peticiones y diagnósticos sin datos.

La decisión es operativa para esta ventana y no elimina los indicadores del catálogo ESIOS. Se reconsiderarán si la API publica valores válidos para una ventana posterior o si cambia el alcance del modelo.
