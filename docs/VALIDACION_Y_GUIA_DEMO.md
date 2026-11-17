# Energy Optimizer — comprobación para demo del 19/11/2026

## Alcance y uso
Modelo **simulado** de 30 MWh/día de carga flexible: comparación S0 (2,5 MWh/h, 08–20) frente a S1 (máximo 7 MWh/h). No es factura real ni medición de planta. La tensión de referencia de 66 kV hace coherente usar el acceso 6.2TD, pero no acredita contrato real. Escenario de la planta: 50.000 m³/día (documentado), 3 kWh/m³, 365 días, 30 MWh y 12,5 MW (hipótesis).

## Comprobación de componentes de la fórmula pública
Fórmula Som Energia: PH = 1,015 * [(PHM+Pc+Sc+Dsv+GdO+POsOm)*(1+Perd)+FE+F] + PTD + CA.

| Elemento | Configuración lista para demo | Estado / tarea | Fuente |
|---|---|---|---|
| PHM | REData, sin truncar precios negativos | Verificar que la serie corresponde a precio OMIE peninsular, unidades y promediado horario de cuartos | Guía Som, pág. 7; https://www.omie.es/es/spot-hoy |
| Pc | P1 0,465; P2 0,213; P3 0,142; P4-P5 0,107; P6 0 €/MWh | Fuente oficial. P6 vacío en la tabla, modelado 0; confirmar aplicación | BOE-A-2025-26705, apartado tercero |
| Sc | 10 €/MWh | HIPÓTESIS: faltan valores horarios exactos de sobrecostes REE de fechas de la demo | Guía Som, pág. 7; https://www.esios.ree.es/ |
| Dsv | 2 €/MWh | HIPÓTESIS: aplicar [0,5*(CoDsvSu+CoDsvBa)+BS3+RAD3] * factor desvío. Valor público 14 % para T1-T3 2026; confirmar T4 con publicación original | Guía Som, págs. 7-8; histórico Som Energia |
| GdO | T1 0,650, T2 0,965, T3 1,405, T4 1,690 €/MWh | T1-T3 contrastados. T4 no reaparece en copia accesible del histórico y se conserva como HIPÓTESIS a verificar, sin presentarlo como dato corroborado | https://www.somenergia.coop/es/historico-tarifa-indexada |
| POsOm | 0,24402 €/MWh | DERIVADO de REE 0,20332 + OMIE 0,04070, costes regulados por programas energéticos. Aproximación de traslado por MWh medido, no certifica facturación exacta | BOE-A-2025-27211 + BOE-A-2025-26705, apartado octavo |
| Perd | 4 % | HIPÓTESIS: los coeficientes 6.2TD P1-P6 están en YAML, pero Som exige corrector horario REE. Mantener 4 % para demo hasta incorporar serie | Guía Som, págs. 5 y 8; Circular CNMC 3/2020 |
| FE | 2 €/MWh | HIPÓTESIS: falta verificar coste unitario que repercute Som Energia 2026. No trasladar directamente importes del PVPC | Guía Som, pág. 8; Orden TED/133/2026 |
| F | 16 €/MWh | HIPÓTESIS fundada en tarifa pública 6.1TD (0,016 €/kWh), no verificada oferta 6.2TD | https://www.somenergia.coop/es/tarifas-luz/altatension-indexada |
| PTD | P1–P6 oficial | DOCUMENTADO 2026: ya en YAML, no duplicar | BOE-A-2025-26348 |
| CA | P1–P6 oficial | DOCUMENTADO 2026, segmento 4, no duplicar | BOE-A-2025-26705 |
| Factor | 1,015 | DOCUMENTADO; no es IVA | Guía Som, pág. 5 |

## Hallazgo de sensibilidad para la daily
Como **S0 y S1 consumen ambos 30 MWh en el mismo día**, un componente aditivo **constante en todas las horas de ese día** (por ejemplo F, FE, Sc constante, Dsv constante o POsOm constante) eleva los dos costes por igual, pero **no cambia el ahorro calculado**. Sí cambia el coste absoluto estimado. En cambio, los **precios de mercado**, los **peajes y cargos por periodo**, **Pc por periodo** y los **componentes horarios** sí pueden alterar las horas elegidas y el ahorro. Las pérdidas constantes cambian la ponderación relativa del spot frente a los peajes/cargos: no son neutras.

## Validaciones ejecutadas
- 28 pruebas unitarias del núcleo + 12 subtests: OK.
- Escenario de prueba **sintético**, martes 13/10/2026 (24 precios inventados para verificar ejecución, **NO datos REData**): S0 = S1 = 30 MWh, S1 menor coste; mantiene signo negativo de precio de mercado; alteración de Sc de 10 a 14 €/MWh mantiene ahorro constante. **No publicar cifras del escenario sintético como resultados del proyecto**.
- No verificado: conexión real a S3, descarga eSIOS/REE, ingesta incremental, integración con interfaz Streamlit; el entorno de prueba no tiene `streamlit` instalado.

## Plan mínimo seguro antes del jueves
1. Coordinar fecha de demostración que tenga 24 horas completas (o 23/25 por cambio horario), precios reales en Silver y valores 2026 de la tarifa; evitar fechas de 2025 si solo hay tarifas 2026.
2. Lucas: verificar que frontend presenta S0/S1 30 MWh, coste, ahorro, negativos y etiqueta "simulación".
3. Claudia: validar valores no arbitrarios Pc y POsOm en esta propuesta; conservar hipótesis visibles y revisar series Sc, Dsv y pérdidas solo si hay tiempo suficiente.
4. Equipo: verificar que no se duplica peaje/cargo; y realizar prueba de extremo a extremo con datos reales.
5. Yomar: solicitar orientación para validar el caso con un cliente industrial: potencia, perfil horario medido, límites físicos y condiciones concretas de una tarifa 6.2TD.

## Archivos
- `config_desaladora.yaml`: configuración revisada. Solo reemplazar `config/config_desaladora.yaml` en la rama de trabajo y revisar diferencias con cambios recientes del equipo.
- `desaladora.py`: adaptación mínima necesaria para que `Pc` admita tabla P1–P6. Reemplazar `src/desaladora.py` solo en una rama, mediante PR. No sobreescribir trabajo más reciente.

**Advertencia:** las condiciones de Som Energia 6.2TD se tramitan individualmente, por lo que la fórmula pública y la simulación no demuestran los términos de una contratación efectiva.
