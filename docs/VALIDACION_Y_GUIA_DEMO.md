# Energy Optimizer — validación de la fórmula de Som Energia para la demo del 19/11/2026

**Revisión:** 17/11/2026 · **Escenario:** desaladora académica conectada a 66 kV, acceso supuesto 6.2TD, Península · **Estado:** simulación, NO factura real ni oferta comercial.

## 1. Dos hallazgos documentales centrales

**(A) Guía oficial de Som Energia: _Guía de funcionamiento. La tarifa indexada de Som Energia_** (PDF aportado por el equipo, 11 páginas). En la página 5 fija la fórmula del precio horario y explica que los conceptos son públicos; las páginas 7 a 9 describen componente a componente las fuentes y su significado. En la página 7 explica el cálculo peninsular de desvíos; en la 8, pérdidas y margen. En la 11 explica que las liquidaciones pueden utilizar los mejores datos disponibles y sufrir revisiones posteriores. La guía **no proporciona por sí sola un fichero con los valores de todos los intervalos de 2026**.

**(B) Repositorio público de GitHub de Som Energia: [`Som-Energia/giscedata_facturacio_indexada_som`](https://github.com/Som-Energia/giscedata_facturacio_indexada_som)**. Su descripción es un módulo de PowerERP/OpenERP para gestionar facturación eléctrica indexada. Archivo relevante: [`tarifes.py`](https://github.com/Som-Energia/giscedata_facturacio_indexada_som/blob/master/tarifes.py). Sirve para **entender la implementación técnica y localizar nombres de series**, por ejemplo `sobrecostes_ree`, `factor_dsv`, `gdos`, `perdclassqh` y `fe`. Para liquidaciones más recientes aparecen referencias a series cuartohorarias, como `codsvsuqh` y `codsvbaqh`. **No equivale a una confirmación de que la versión pública sea exactamente la usada hoy para contratos 6.2TD**, ni permite deducir que los valores del YAML se hayan descargado de REE.

**Fórmula publicada (guía, pág. 5):**

`PH = 1,015 × [ (PHM + Pc + Sc + Dsv + GdO + POsOm) × (1 + Perd) + FE + F ] + PTD + CA`

Todos los componentes monetarios del YAML están expresados en **€/MWh**, no €/kWh. `Perd` es una fracción (por ejemplo `0.04` = 4 %). El multiplicador `1,015` **no es el IVA**. Los peajes y cargos están **dentro de PH**, y no deben sumarse de nuevo al coste de energía.

## 2. Tabla completa: significado, procedencia, valor utilizado y grado de certeza

| Variable | Qué representa y cómo se obtiene | Estado de la demo / YAML | Fuente exacta y próximo paso |
|---|---|---|---|
| **PHM** (precio horario del mercado) | Precio spot de compraventa de electricidad en el mercado diario peninsular. Cambia por intervalo. | **Dato de entrada:** REData; NO se fija un importe en el YAML. | **Som guía pág. 7**; [OMIE spot](https://www.omie.es/es/spot-hoy). Validar que el indicador usado por REData es comparable al precio OMIE de referencia y que coinciden fecha, zona, huso y granularidad. Conservar precios negativos. |
| **Pc** (pagos por capacidad) | Importe regulado por disponibilidad de generación, distinto según periodo tarifario. | **Tabla 2026:** P1 0,465; P2 0,213; P3 0,142; P4 0,107; P5 0,107; P6 0,000 **provisional** €/MWh. Sustituye la antigua constante 0,50. | **Som guía pág. 7**; [Orden TED/1524/2025](https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26705), apartado de pagos por capacidad. **El cero de P6 es una interpretación de la celda sin importe explícito; revisar su aplicación antes de certificarlo**. |
| **Sc** (sobrecostes del sistema) | Costes de ajustes y restricciones técnicas de operación del sistema calculados por REE; deben variar con el intervalo. | **10,00 €/MWh — HIPÓTESIS FIJA**; todavía no se han descargado las series para el día de la demo. | **Som guía pág. 7**; [REE/eSIOS](https://www.esios.ree.es/); **repositorio GitHub `tarifes.py`** como guía para identificación de `sobrecostes_ree` y dependencias. No asumir que un indicador agregado es la suma contractual exacta sin revisar unidades, vigencia y solapamiento con Dsv. |
| **Dsv** (desvíos) | Coste por diferencias entre energía programada y utilizada. Para la Península: `[(CoDsvSu + CoDsvBa)/2 + BS3 + RAD3] × factor_desvío`. | **2,00 €/MWh — HIPÓTESIS FIJA**. El **factor** de Som Energia **0,14 está verificado** para T1–T4 2026, pero no se ha calculado Dsv con series reales. | **Som guía págs. 7–8**; [histórico Som Energia](https://www.somenergia.coop/es/historico-tarifa-indexada) (14 % cada trimestre de 2026); [eSIOS](https://www.esios.ree.es/); código `tarifes.py` (`factor_dsv` y variantes de series cuartohorarias). **No multiplicar 0,14 por PHM**; aplicar la fórmula publicada. |
| **GdO** (garantías de origen) | Certificados que garantizan el origen renovable; Som Energia publica el coste unitario trimestral. | **DOCUMENTADO 2026:** T1 0,650; T2 0,965; T3 1,405; T4 1,690 €/MWh. | **Som guía pág. 8**; [histórico oficial Som Energia](https://www.somenergia.coop/es/historico-tarifa-indexada), tabla de GdO y Dsv. Publicados originalmente en €/kWh: multiplicar por 1.000. **T4 ya está confirmado públicamente**. |
| **POsOm** (operadores REE y OMIE) | Retribución regulada del operador del sistema y del mercado. | **0,24402 €/MWh — DERIVADO:** 0,20332 REE + 0,04070 OMIE. Referencia de demo, no reconstrucción de liquidación individual. | **Som guía pág. 8**; [BOE-A-2025-27211](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-27211) (REE) y [BOE-A-2025-26705](https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26705) (OMIE). Revisar base de energía programada frente a consumo medido antes de afirmar exactitud contractual. |
| **Perd** (pérdidas del sistema) | Coeficientes para trasladar energía desde el punto de consumo a barras de central, incluyendo ajuste horario de REE. Multiplican el bloque `PHM + Pc + Sc + Dsv + GdO + POsOm`. | **0,04 = 4 % — HIPÓTESIS FIJA**. El YAML conserva coeficientes regulatorios 6.2TD P1 5,2 %, P2 5,4 %, P3 4,9 %, P4 5,0 %, P5 3,5 %, P6 5,4 % como contexto, pero NO se usan directamente como fórmula completa. | **Som guía págs. 5 y 8**, **Dilan págs. 3 y 8**, [CNMC Circular 3/2020](https://www.boe.es/buscar/doc.php?id=BOE-A-2020-1066), REE/eSIOS y `tarifes.py` (`perdclassqh`). Falta recuperar el corrector temporal, verificar definición y granularidad. |
| **FE** (Fondo Nacional de Eficiencia Energética) | Coste por energía comercializada relacionado con la obligación regulatoria de eficiencia energética. | **2,00 €/MWh — HIPÓTESIS FIJA**. No consta verificado como repercusión exacta de Som Energia. | **Som guía págs. 6 y 8**; [Orden TED/133/2026](https://www.boe.es/buscar/doc.php?id=BOE-A-2026-4522), obligaciones del FNEE; `tarifes.py` consulta el coeficiente `fe`. **No deducir directamente el FE de la obligación anual total ni copiar un valor PVPC**. Necesita publicación comercial o confirmación explícita de Som Energia. |
| **F** (franja/margen comercial) | Margen que define Som Energia para comercialización; puede cambiar con preaviso. | **16,00 €/MWh — REFERENCIA PÚBLICA EXTRAPOLADA**, no oferta 6.2TD confirmada. | **Som guía pág. 8**; [histórico oficial](https://www.somenergia.coop/es/historico-tarifa-indexada) muestra **0,016 €/kWh** en 3.0TD y 6.1TD. La guía permite interpretar F como margen de cooperativa, pero **el histórico consultado no muestra fila 6.2TD**. Confirmación de caso particular: Som Energia (directamente) o Yomar si dispone de contrato comparable. |
| **PTD** (peajes) | Precio regulado de uso de las redes de transporte y distribución, distinto según periodo P1–P6. | **DOCUMENTADO 2026:** P1 14,736; P2 7,202; P3 2,542; P4 1,254; P5 0,062; P6 0,020 €/MWh. | **Som guía pág. 9**; [CNMC Resolución 18/12/2025](https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26348). Ya incluidos en la fórmula, NO duplicar. |
| **CA** (cargos) | Importes regulados para financiar costes del sistema, por segmento y periodo. Para 6.2TD corresponde segmento 4. | **DOCUMENTADO 2026:** P1 9,144; P2 6,773; P3 3,658; P4 1,829; P5 1,172; P6 0,732 €/MWh. | **Som guía pág. 9**; [Orden TED/1524/2025](https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26705), segmento 4. Ya incluidos, NO duplicar. |
| **1,015** (multiplicador) | Multiplicador fijado en la fórmula pública sobre el bloque entre corchetes. | **1,015 — DOCUMENTADO**. | **Som guía pág. 5**. No es IVA ni se debe aplicar otra vez fuera de la fórmula. |

**Leyenda de estados:** `documented` = valor publicado aplicable identificado; `derived` = cálculo documentado con referencias públicas, pero revisar equivalencia con la base facturada; `hypothesis` = decisión de simulación, no dato contractual confirmado. Encontrar el repositorio **no convierte una hipótesis en un valor documentado**: deben obtenerse las series reales correspondientes.

## 3. Qué se ha corregido y qué NO se ha corregido

**Archivos del paquete:** `config_desaladora.yaml` (ruta de destino `config/config_desaladora.yaml`) y `desaladora.py` (ruta `src/desaladora.py`) proceden de la propuesta previa de la demo; `VALIDACION_Y_GUIA_DEMO.md` es nuevo y ampliado.

**Cambios funcionales y de configuración respecto al proyecto original del 13/11:**
- `Pc` pasa de un escalar 0,50 a valores P1–P6; `src/desaladora.py` admite tanto escalar como diccionario por periodos.
- `POsOm` pasa de 0,20 estimado a 0,24402 derivado de valores regulatorios (con advertencia sobre base de aplicación).
- Se añade en YAML el factor público de desvíos 0,14 por trimestre **como metadato**: el motor todavía utiliza `dsv_eur_mwh = 2`, no calcula Dsv real.
- Se documentan los cuatro GdO como confirmados, incluida T4; y se añaden en `fuentes_demo` la guía oficial, el nombre del repositorio de GitHub, su archivo `tarifes.py` y enlaces a fuentes públicas.
- **NO se ha implementado aún extracción temporal de Sc, Dsv y Perd ni recalculado el FE contractual**. El YAML mantiene 10, 2, 4 % y 2, respectivamente. **No decir que reproduce la factura exacta de Som Energia.**

La guía y el código público de Som Energia son referencias complementarias: **guía = explicación normativa/comercial de la fórmula; repositorio = pistas de implementación y nombres de componentes**. La guía está aportada por el equipo; el código está disponible en GitHub. Ninguno demuestra un contrato firmado con la desaladora.

## 4. Por qué una demo con hipótesis es defendible

La desaladora procede del TFM mencionado por Dilan: capacidad de referencia **50.000 m³/día** y conexión prevista a **66 kV**, compatible con acceso **6.2TD**. Se simulan **30 MWh/día flexibles** sobre un consumo total estimado a partir de **3 kWh/m³**; se compara **S0 = 2,5 MWh/h de 08:00 a 20:00** con **S1 = redistribuir 30 MWh con máximo 7 MWh/h**. El documento de Dilan especifica que estos son **supuestos académicos, no medidas físicas ni contrato real**.

S0 y S1 consumen exactamente los mismos 30 MWh dentro del mismo día; un coste **aditivo y constante por MWh en todas las horas** se suma igual a ambos escenarios y **no cambia la diferencia de costes**, aunque sí los euros absolutos. Si las series reales de Sc o Dsv **varían por hora**, sí pueden cambiar el ahorro y la selección de horas. Las pérdidas también alteran la ponderación del precio variable respecto a PTD y CA. No usar esta propiedad para afirmar que da igual recuperar los valores horarios.

**Validaciones imprescindibles antes de enseñar números:** precios REData contrastados con precio de mercado de referencia, fechas de 2026 con tablas 2026, asignación P1–P6 según calendario peninsular (incluidos cambios de horario), precios negativos sin truncar, 30 MWh en S0 y en S1, límite 7 MWh/h, no duplicar PTD ni CA y desglose que reconstruya S0, S1 y ahorro.

## 5. Estado de las pruebas y límites conocidos

La propuesta previa pasó **28 pruebas unitarias del núcleo y 12 subtests**, más un escenario sintético de 24 horas con precios inventados; **no son resultados con datos reales**. Esta versión mantiene el mismo motor de cálculo y solo revisa datos/documentación. **No se ha verificado la ingesta completa desde S3, una ejecución de frontend Streamlit ni la integración con ramas recientes del equipo.** Se recomienda comparar los archivos por `git diff` e integrar mediante PR sin sobrescribir cambios recientes.

## 6. Prioridad antes del jueves y preguntas para Yomar

**Para la demo:** cerrar prueba punta a punta en una fecha real disponible en S3, con un resultado reproducible y una tabla de componentes con etiquetas `documented` / `derived` / `hypothesis`. El proyecto no depende de obtener Sc/Dsv/Perd precisos para mostrar el algoritmo, pero sí para afirmar que reproduce el precio indexado de una hora real.

**Después / con Yomar:** conseguir contacto o documentación de un contrato industrial **6.2TD**, margen F específico y método FE repercutido; además validar perfiles horarios y restricciones operativas de una planta real. Se puede contactar también directamente con Som Energia. No presentar una simulación académica como facturación industrial auditada.

## 7. Fuentes clave y trazabilidad

1. **Guía oficial de Som Energia**, _Guía de funcionamiento. La tarifa indexada de Som Energia_, PDF entregado por el equipo, **págs. 5–9** (fórmula, variables), **pág. 11** (facturación con datos disponibles).
2. **Repositorio oficial público de Som Energia:** [`Som-Energia/giscedata_facturacio_indexada_som`](https://github.com/Som-Energia/giscedata_facturacio_indexada_som); **código:** [`tarifes.py`](https://github.com/Som-Energia/giscedata_facturacio_indexada_som/blob/master/tarifes.py). No presuponer que la rama `master` corresponde exactamente al motor de facturación usado en producción en 2026.
3. **Som Energia, histórico de tarifa indexada:** https://www.somenergia.coop/es/historico-tarifa-indexada (GdO y factor Dsv T1–T4 de 2026, franja de tarifas publicadas).
4. **REE/eSIOS:** https://www.esios.ree.es/ (series de sobrecostes, desvíos y pérdidas; aún pendientes de integrar).
5. **OMIE:** https://www.omie.es/es/spot-hoy (precio spot de referencia).
6. **BOE:** https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26705 (Pc y CA); https://www.boe.es/buscar/doc.php?id=BOE-A-2025-26348 (PTD); https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-27211 (REE); https://www.boe.es/buscar/doc.php?id=BOE-A-2026-4522 (FNEE).
7. **Documento de Dilan**, _Disponibilidad de precios REData_, págs. 1–3, 8 y 11–14 (base del escenario y condiciones de validez).
