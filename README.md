# odb-challenge-energy-optimizer
Open Data Business Challenge - Energy Optimizer project (Case 4)

#  Energy Optimizer

> **No consumas menos. Consume en el momento adecuado.**

Energy Optimizer analiza cómo reducir el coste de la carga eléctrica flexible de una planta industrial desplazando el consumo hacia las horas de menor precio, sin reducir la energía consumida.

## 1. Problema y decisión

Una planta industrial compra electricidad indexada al precio del mercado diario y dispone de **30 MWh/día de carga flexible** que puede desplazarse dentro del mismo día.

La operación actual (**S0**) distribuye esta carga entre las **08:00 y las 20:00**, a razón de **2,5 MWh por hora**. El escenario optimizado (**S1**) mantiene los mismos 30 MWh diarios, pero los asigna a las horas de menor precio respetando una capacidad máxima de **7 MWh por hora**.

La pregunta de negocio es:

> **¿Cuánto puede ahorrar la planta en un año consumiendo su carga flexible en las horas de menor precio del mercado diario?**

El objetivo no es reducir el consumo, sino mejorar la decisión de **cuándo consumir**.

## 2. Hipótesis

1. **Es posible ahorrar sin consumir menos:** desplazar la misma energía hacia horas de menor precio puede reducir el coste.
2. **El ahorro varía entre días:** los precios presentan variabilidad tanto diaria como intradiaria.
3. **Las horas más baratas no son necesariamente nocturnas:** la ventana óptima debe determinarse para cada día.
4. **El mix de generación influye en el patrón de precios:** especialmente la generación solar y eólica.

## 3. Fuentes

| Fuente | Datos utilizados | Acceso | Fecha de descarga | Licencia / atribución |
|---|---|---|---|---|
| REData · Red Eléctrica | Precio del mercado diario | API REST JSON | [PENDIENTE] | [PENDIENTE] |
| [SEGUNDA FUENTE] | [PENDIENTE] | [PENDIENTE] | [PENDIENTE] | [PENDIENTE] |

## 4. Calidad de datos

| Fuente | Registros | % nulos en campos clave | Duplicados | % cruce | Decisión adoptada |
|---|---:|---:|---:|---:|---|
| REData - precios | [PENDIENTE] | [PENDIENTE] % | [PENDIENTE] | [PENDIENTE] % | Agregación a resolución horaria y controles de calidad |
| [SEGUNDA FUENTE] | [PENDIENTE] | [PENDIENTE] % | [PENDIENTE] | [PENDIENTE] % | [PENDIENTE] |

### Decisiones de tratamiento

- **Resolución temporal:** desde el 1 de octubre de 2025 el mercado diario opera en periodos de 15 minutos. Para el análisis, los precios se llevan a resolución horaria mediante la media de los valores cuartohorarios de cada hora.
- **Cambios de hora:** los días de 23 o 25 horas se tratan explícitamente para no asumir que todos los días tienen 24 horas.
- **Precios negativos:** como decisión metodológica del equipo, los precios negativos se sustituyen por cero para el cálculo, conservando el precio original en la capa Bronze para mantener la trazabilidad.
- **Horas incompletas:** se controla que cada hora disponga de sus cuatro observaciones cuartohorarias. El tratamiento definitivo de las horas incompletas está pendiente de cerrar antes de la entrega.

## 5. Solución y resultados

La solución compara diariamente dos escenarios para la carga flexible de la planta:

- **S0 · Operación actual (baseline):** 30 MWh/día distribuidos entre las 08:00 y las 20:00, a razón de 2,5 MWh por hora.
- **S1 · Operación optimizada:** mantiene los mismos 30 MWh/día, pero los asigna a las horas de menor precio, respetando una capacidad máxima de 7 MWh por hora.

### Optimización diaria

Para cada día se aplica el siguiente procedimiento:

1. Obtener los precios horarios del mercado diario.
2. Ordenar las horas de menor a mayor precio.
3. Asignar la carga flexible empezando por las horas más baratas.
4. Mantener un consumo total de 30 MWh/día sin superar 7 MWh en ninguna hora.
5. Calcular el coste diario de S0 y S1.
6. Calcular el ahorro diario como la diferencia entre el coste de S0 y el coste de S1.

### Decisiones metodológicas

- La comparación entre S0 y S1 se realiza **día a día sobre un año completo**. No se extrapola el resultado de un único día al resto del año.
- S0 y S1 utilizan **la misma energía flexible diaria (30 MWh)** y el mismo límite máximo de **7 MWh/h**. La diferencia entre ambos escenarios es únicamente el momento en el que se consume esa energía.
- Los días de cambio horario de **23 o 25 horas** se tratan explícitamente en el análisis.
- Los precios utilizados por el optimizador se encuentran a **resolución horaria**. Cuando los datos de origen tienen resolución cuartohoraria, se agregan previamente a nivel horario.
- El escenario S1 utiliza los precios conocidos del mercado diario. La previsión de precios no forma parte del núcleo actual, ya que el precio del día siguiente se publica tras la casación y la programación puede realizarse posteriormente.

### Modelo frente a baseline

| Métrica | Baseline S0 | Modelo S1 | Mejora | Lectura de negocio |
|---|---:|---:|---:|---|
| Coste anual | [PENDIENTE] € | [PENDIENTE] € | [PENDIENTE] € | Ahorro anual de la carga flexible |
| Ahorro relativo | — | [PENDIENTE] % | [PENDIENTE] % | Reducción del coste frente a la operación actual |

Además del resultado anual, se analizará la **evolución mensual del ahorro**, las horas más utilizadas por el optimizador y los factores que explican las diferencias de ahorro entre días.
