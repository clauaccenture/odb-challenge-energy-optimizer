# Comparación CNMC y MIBGAS

## Objetivo

Antes de retirar CNMC se comparó su recurso `producto_diario_d1` con la serie MIBGAS D+1. La finalidad era comprobar si ambas fuentes eran duplicados exactos y justificar la elección de una única fuente operativa.

## Método

Se utilizaron los outputs procesados disponibles localmente en ese momento. Del recurso CNMC se conservaron únicamente los registros con `source_resource == "producto_diario_d1"`. Estos datos pertenecían a la carpeta `data/`, que no se versiona, y ya no forman parte del estado actual del proyecto.

La comparación se realizó por `fecha_negociacion`, porque el output CNMC no conserva una fecha de entrega para este recurso. Se comparó `precio_eur_mwh` y se calcularon coincidencias exactas y diferencias absolutas.

El siguiente código documenta la comparación realizada antes de retirar CNMC. No es ejecutable con el estado actual del repositorio sin recuperar previamente esos datos históricos:

```python
import json
from pathlib import Path

import pandas as pd

root = Path.cwd()
cnmc = pd.DataFrame(json.loads(
    (root / "data/processed/cnmc/cnmc_diario.json").read_text(encoding="utf-8")
))
mibgas = pd.DataFrame(json.loads(
    (root / "data/processed/mibgas/mibgas_d1.json").read_text(encoding="utf-8")
))

cnmc = cnmc[cnmc["source_resource"].eq("producto_diario_d1")].copy()
cnmc["fecha_negociacion"] = pd.to_datetime(cnmc["fecha_negociacion"]).dt.date
mibgas["fecha_negociacion"] = pd.to_datetime(mibgas["fecha_negociacion"]).dt.date

comparison = cnmc[["fecha_negociacion", "precio_eur_mwh"]].merge(
    mibgas[["fecha_negociacion", "precio_eur_mwh"]],
    on="fecha_negociacion",
    suffixes=("_cnmc", "_mibgas"),
)
comparison["abs_difference"] = (
    comparison["precio_eur_mwh_cnmc"]
    - comparison["precio_eur_mwh_mibgas"]
).abs()
```

## Resultado

| Métrica | Resultado |
|---|---:|
| Registros CNMC D+1 | 608 |
| Registros MIBGAS D+1 | 730 |
| Solapamiento por fecha de negociación | 608 |
| Cobertura CNMC | 01/10/2024 - 31/05/2026 |
| Cobertura MIBGAS por fecha de entrega | 01/10/2024 - 30/09/2026 |
| Coincidencias exactas | 14 (2,30 %) |
| Coincidencias con tolerancia de 0,01 EUR/MWh | 23 (3,78 %) |
| Precio medio CNMC | 38,648 EUR/MWh |
| Precio medio MIBGAS | 38,635 EUR/MWh |
| Diferencia media con signo | 0,013076 EUR/MWh |
| Desviación típica de la diferencia | 0,613290 EUR/MWh |
| Diferencia absoluta media | 0,395477 EUR/MWh |
| Diferencia absoluta mediana | 0,010000 EUR/MWh |
| Percentil 90 de la diferencia absoluta | 0,883000 EUR/MWh |
| Percentil 95 de la diferencia absoluta | 1,316500 EUR/MWh |
| Diferencia absoluta máxima | 3,42 EUR/MWh |
| Diferencia absoluta media relativa | 0,9727 % |
| Días con diferencia absoluta <= 1 EUR/MWh | 91,28 % |
| Días con diferencia absoluta <= 2 EUR/MWh | 98,36 % |

La diferencia media con signo es prácticamente cero, por lo que no se observa un sesgo sistemático de una fuente frente a la otra. La diferencia absoluta media es moderada respecto al precio medio y el 91,28 % de las observaciones difiere en menos de 1 EUR/MWh. Las coincidencias exactas son pocas porque las fuentes no son copias byte a byte y pueden aplicar criterios de publicación o redondeo distintos.

La comparación usando `fecha_entrega` como clave produce un resultado aún menos coincidente: 6 coincidencias exactas, 1,64 % dentro de 0,01 EUR/MWh, una diferencia absoluta media de 0,762681 EUR/MWh y una máxima de 13,06 EUR/MWh.

## Decisión

Se mantuvo MIBGAS como única fuente operativa D+1 porque cubre todo el periodo del modelo hasta el 30/09/2026, mientras que CNMC solo llega hasta el 31/05/2026. Además, MIBGAS es la fuente oficial directa del producto utilizado y mantener ambas ingestas añadiría complejidad sin una necesidad operativa concreta. Aunque los precios son próximos, no son idénticos; por ello, la retirada de CNMC responde a cobertura y simplicidad operativa, no a una igualdad exacta entre las series. Los componentes CNMC se eliminaron tras conservar esta comparación como registro de la decisión.
