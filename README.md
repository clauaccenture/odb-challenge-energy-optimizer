#  Energy Optimizer

> **No consumas menos. Consume en el momento adecuado.**

Energy Optimizer analiza cómo reducir el coste de la carga eléctrica flexible de una planta industrial desplazando el consumo hacia las horas de menor precio, sin reducir la energía consumida.

### Backend de demo: desaladora y contrato indexado de referencia

El modo optativo `--config` de [03_gold_redata.py](notebooks/03_gold_redata.py)
lee [config_desaladora.yaml](config/config_desaladora.yaml) y calcula un escenario
separado con la formula publicada de Som Energia. **No es una oferta 6.2TD, contrato
firmado, factura real ni validacion de la flexibilidad de una planta.**
El modo Gold habitual conserva su comportamiento. El frontend permite elegir
**Desaladora · Som Energia (simulado)** sin sustituir las comparativas anteriores.

Para desarrollar en el PC sin descargar datos de S3, usar las pruebas sinteticas
(S3 simulado, sin conexiones AWS). Desde la raiz, con el entorno virtual activado,
ejecutar los comandos uno a uno. En Windows:

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest src\tests\test_config_loader.py src\tests\test_tarifas_6_2td.py notebooks\tests\test_gold_redata_peajes.py -q
```

En Linux/EC2, despues de actualizar el codigo y activar el entorno, el modo `--s3`
lee el Silver publicado y escribe los resultados directamente en S3, en memoria,
**sin descargar ni guardar ficheros de datos en disco**:

```bash
python -m pip install -r requirements.txt
export S3_BUCKET="energy-optimizer-grupo4"
export REDATA_S3_PREFIX="redata"
python notebooks/03_gold_redata.py --config config/config_desaladora.yaml --s3
```

Cambiar bucket/prefijo si la publicacion Silver utiliza otra ubicacion. Se lee
exactamente `s3://S3_BUCKET/processed/REDATA_S3_PREFIX/precios_horarios.json`,
sin alternativa local si falta el objeto o los permisos. El YAML del caso sigue
versionado en el repositorio. La ventana elegida en ese YAML se aplica sobre los
datos publicados: no se inventan precios ni se enumeran todos los objetos del bucket.

Silver contiene la media de cuatro precios cuartohorarios para cada hora real.
No se repiten llamadas a REData ni se vuelve a truncar el spot negativo.
Es una aproximacion horaria, no una replica de la liquidacion cuartohoraria del contrato.

**Precio marginal utilizado tanto para S0 como para optimizar S1 (EUR/MWh):**

```text
PH = 1.015 * [(spot + Pc + Sc + Dsv + GdO + POsOm) * (1 + Perd) + FE + F] + PTD + CA
```

PTD y CA se incorporan una sola vez. Los importes y el calendario 6.2TD siguen en
[tarifas_6_2td.py](src/tarifas_6_2td.py), sin duplicarse en el YAML. A diferencia
del modo Gold anterior, el caso reoptimiza con PH, no solo con el spot.

| Dato | Tratamiento en la demo |
|---|---|
| Formula y factor 1.015 | Publicados por Som Energia; este factor no es IVA ni IEE. |
| Peajes/cargos y calendario | Referencias regulatorias 2026 del modulo de tarifas. |
| GdO T1/T2/T3/T4 | 0.650 / 0.965 / 1.405 / 1.690 EUR/MWh, segun el historico titulado «sin impuestos». La aplicacion a este contrato simulado y el criterio fiscal se declaran como hipotesis. |
| F | 16 EUR/MWh: extrapolacion del precio publico de 6.1TD, no oferta confirmada 6.2TD. |
| Pc / Sc / Dsv / POsOm / FE | 0.5 / 10 / 2 / 0.2 / 2 EUR/MWh: constantes ilustrativas, **no series oficiales ni estimaciones calibradas**. Dsv no es un recargo del 14 % sobre el spot. |
| Perd | 4 % constante supuesto, no coeficientes reales de perdidas REE. |
| Precios negativos | Spot y PH se conservan; una liquidacion PH negativa es una hipotesis, no una condicion contractual confirmada. |
| Operacion | 150 MWh/dia estimados: 30 flexibles y 120 no flexibles. Los 120 se reparten uniformemente entre las 23/24/25 horas del dia. No es una curva medida. |
| Potencia | 12.5 MW supuestos en cada P1-P6, como limite de potencia media horaria de la planta completa. No se calculan importes de potencia, excesos cuartohorarios ni picos dentro de la hora. |

El balance agregado respeta la energia y la potencia media supuestas; **no prueba
que membranas, bombas, produccion de agua o almacenamiento permitan esa operacion**.
No se ejecuta una programacion con restricciones de rampa, arranque o deposito:
si se activan en el YAML, el backend falla explicitamente en vez de ignorarlas.
Esas restricciones necesitaran un modelo operativo LP/MILP segun corresponda.
Tampoco se aceptan otros anos/tarifas, impuestos o componentes no implementados.

Por defecto `fecha_inicio` y `fecha_fin` son `null`: se toma **toda la cobertura
Silver disponible dentro de la vigencia tarifaria 2026**, incluyendo noviembre
y diciembre si estan publicados. No hay un corte fijo en septiembre ni octubre.
Se pueden fijar fechas expresamente para un ensayo acotado. Las horas de otros
anos no se valoran con tarifas 2026: se informa de cuantas se excluyen en consola
y en `metadata.json`. Para incluirlas con tarifa hacen falta importes y calendario
de su ano correspondiente.
No se anualizan resultados. Las fechas ausentes o incompletas se registran en el
resumen diario sin ahorro ficticio; un mes sin dias validos tiene costes nulos
(no cero). Los duplicados y precios no finitos provocan error.

La salida S3, independiente del Gold anterior, se guarda por ejecucion bajo
`outputs/desaladora_som_energia/runs/<id>/`:

- `programacion_horaria.parquet`: timestamps UTC y locales con desfase, spot,
  componentes de PH, precio indexado, consumos S0/S1 flexibles y totales de planta,
  potencia supuesta y costes del **termino de energia antes de impuestos**.
- `resumen_diario.parquet` y `resumen_mensual.parquet`: costes de energia, ahorro y
  cobertura; el coste no flexible es identico en S0/S1 y no genera ahorro.
- `metadata.json`: YAML completo con notas/fuentes, clasificacion
  `documented`/`hypothesis`/`derived`, huellas SHA-256 de configuracion, Silver y
  resultados, vigencia de tarifas y cobertura. Los parametros calculados (precio,
  consumo no flexible y costes) son derivados, no mediciones.

`outputs/desaladora_som_energia/latest.json` apunta al `metadata.json` de la ultima
ejecucion publicada correctamente. Ese metadata identifica las claves exactas y
huellas de sus tres Parquet, el origen Silver y su VersionId si el bucket lo ofrece.
El puntero se actualiza **solo despues** de subir todos los resultados: un fallo
de calculo/subida no publica una mezcla de ejecuciones. Un fallo de subida puede
dejar una ejecucion parcial sin referenciar, que debe limpiarse posteriormente.
El dashboard resuelve este puntero una vez y lee solo esas claves, comprobando
las huellas y la coherencia de los resultados.
El rol IAM necesita `s3:GetObject` sobre el Silver y `s3:PutObject` sobre
`outputs/desaladora_som_energia/*` (y permisos KMS si el bucket los requiere).

No sobrescribe los Parquet anteriores. No se incluye la factura completa:
potencia fija, excesos, reactiva, alquiler,
bono social, IVA e IEE estan fuera.

### Frontend del caso desaladora

En las tres vistas de resultados, seleccionar **Desaladora · Som Energia
(simulado)** para consultar costes y ahorro de la carga flexible reoptimizada
con PH. La programacion diaria muestra de un vistazo las horas elegidas y la
energia a mover: en este caso, 4 horas de 7 MWh y 1 hora de 2 MWh.
Los costes S0/S1 y ahorro se resumen en una tarjeta del dia, solo para la carga
flexible; no se muestran costes de la planta completa. El desglose de energia
queda plegado como detalle opcional. El CSV tiene siete columnas con hora,
precio indexado, carga S0/S1, coste S0/S1 y ahorro. Conserva todas las horas
del dia para cuadrar los totales; no cambia el plan calculado en Gold.

La cuarta vista, **Caso desaladora**, utiliza siempre la ejecucion Som, aunque
este seleccionado otro modo de coste. Resume los datos del TFM, los supuestos
electricos y contractuales, la formula Som y la leyenda de todos sus terminos,
distinguiendo valores publicados, derivados y supuestos. La cobertura, fuentes
y peajes por periodo quedan en una seccion desplegable. No muestra comandos,
YAML, JSON, hashes ni metadatos tecnicos. La informacion se toma de la ejecucion
publicada, no de la configuracion actual del disco.

Antes de probar mediante SSM, publicar el caso con el comando `--config ... --s3`
anterior y reiniciar la app con el codigo actualizado. En EC2, mantener
`S3_BUCKET` configurado tambien al iniciar Streamlit; pulsar **Actualizar datos
de S3** tras una nueva publicacion. El rol del dashboard necesita `s3:GetObject`
sobre `outputs/desaladora_som_energia/*`. El front no ejecuta el optimizador,
no escribe en S3 y no recurre a datos locales si falta la publicacion.
Detalles de acceso y pruebas en [app/README.md](app/README.md).

Para una ejecucion local voluntaria, `--config ... --no-s3` conserva la lectura
de `data/processed/redata/precios_horarios.json` y escribe en
`data/outputs/desaladora_som_energia/`. No es necesario para las pruebas del PC.
Los modos `--s3` y `--no-s3` son mutuamente excluyentes; el caso exige elegir uno.
El Gold anterior, sin `--config`, conserva sus opciones y comportamiento.

Fuentes consultadas el 12/11/2026:
[formula](https://www.somenergia.coop/es/servicios/como-calculamos-el-precio),
[historico de GdO](https://www.somenergia.coop/es/historico-tarifa-indexada),
[referencia comercial 6.1TD](https://www.somenergia.coop/es/tarifas-luz/altatension-indexada)
y [condiciones de alta tension](https://es.support.somenergia.coop/article/1343-tarifas-de-alta-tension-6-1td-6-2td-6-3td-y-6-4td-indexadas).

Pruebas del caso y regresion del backend (el runner `pytest` es dependencia de desarrollo):

```text
python -m pytest src/tests/test_config_loader.py src/tests/test_tarifas_6_2td.py notebooks/tests/test_gold_redata_peajes.py -q
```

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
4. **El mix de generación influye en el patrón de precios:** especialmente la generación solar.

## 3. Fuentes

| Fuente | Datos utilizados | Acceso | Fecha de descarga | Licencia / atribución |
|---|---|---|---|---|
| REData · Red Eléctrica | Hora, precio del mercado diario | API REST JSON sin token (`https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real`) | 15/10/2026 | Red Eléctrica de España (REData) |
| AEMET OpenData | Fecha, provincia, temperatura máxima, mínima y media, hora temperatura máxima y mínima | API REST con clave gratuita (`https://opendata.aemet.es`) | 18/10/2026 | Agencia Estatal de Meteorología (AEMET) |

## 4. Calidad de datos

| Fuente | Registros | % nulos en campos clave | Duplicados | % cruce |
|---|---:|---:|---:|---:|
| REData | 35.040 cuartos de hora  | 0 % | 0 | 100 % |
| AEMET | 305.398 registros  (299.073 tras limpieza) | tmax 0,04 %; tmin 0,09 %; tmed 0,13 %; | 0 | 100 % |

### Decisiones de tratamiento

- **Resolución temporal (REData):** el mercado diario opera en periodos de 15 minutos. Los precios se llevan a resolución horaria mediante la media de los valores cuartohorarios de cada hora.
- **Precios negativos (REData):** como decisión del equipo, los precios negativos se sustituyen por cero para el cálculo, conservando el precio original en la capa Bronze.
- **Horas incompletas (REData):** se controla que cada hora disponga de sus cuatro observaciones cuartohorarias. En el periodo analizado no se ha detectado ninguna hora incompleta. El proceso de calidad emite un aviso si una hora no tiene sus cuatro cuartos de hora, y el proceso Gold omite los días cuyo número de horas no sea 23, 24 o 25.
- **Cambios de hora (REData):** los días de cambio horario tienen 23 o 25 horas (29/03/2026 y 26/10/2025) y se tratan sin asumir que todos los días tienen 24.
- **Decimales (AEMET):** la API de AEMET devuelve los valores numéricos con coma decimal. En el tratamiento de la fuente se sustituyen las comas por puntos para poder convertirlos a número y evitar errores en el procesado.
- **Provincias (AEMET):** se unifica el nombre de la provincia.
- **Nulos (AEMET):** Se eliminan las filas sin ninguna temperatura (2,07 % de las 305.398). Las horas de temperatura máxima y mínima no válidas se dejan como nulo, nunca como 0. Los porcentajes de nulos de la tabla 4 se calculan **después** de esta limpieza.
- **Descarga de AEMET (capa raw):** la API solo permite descargar tramos de 15 días por petición, por lo que el script de ingesta divide el periodo en tramos y se ejecuta con un único comando. Los ficheros originales no se modifican.
- **Estructura de la capa silver (AEMET):** se conserva un registro por estación y día, sin agregar. Las localidades no se agrupan por provincia, porque REData es nacional; la temperatura media de España y los extremos se calculan en la capa Gold.
- **Valores fuera de rango (AEMET):** las temperaturas fuera de un rango físico posible se pasarían a nulo; en este periodo no se ha detectado ninguna.
- **Cruce entre fuentes:** la clave es la fecha. REData y AEMET cubren los 365 días del periodo (100 % de cruce), por lo que no se excluye ningún día. Si faltara algún día de una de las fuentes, se excluiría del análisis que relaciona precio y temperatura, pero se mantendría en el cálculo del ahorro, que solo usa los precios.

## 5. Solución y resultados

La solución compara diariamente dos escenarios para la carga flexible de la planta:

- **S0 · Operación actual (baseline):** 30 MWh/día distribuidos entre las 
08:00 y las 20:00, a razón de 2,5 MWh por hora.
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
- Los precios utilizados por el optimizador se encuentran a **resolución horaria**. Cuando los datos de origen tienen resolución cuartohoraria, se agregan previamente a nivel horario.
- El escenario S1 utiliza los precios conocidos del mercado diario. La previsión de precios no forma parte del núcleo actual, ya que el precio del día siguiente se publica tras la casación y la programación puede realizarse posteriormente.
- Cuando dos o más horas presentan exactamente el mismo precio, el optimizador prioriza las horas diurnas (dentro de la franja 08:00 a 17:00) frente a las nocturnas y, si persiste el empate, la hora más temprana. Esta regla permite mantener una programación más cercana a la operación habitual de la planta cuando no existe diferencia económica entre las alternativas.

### Modelo frente a baseline

| Métrica | Baseline S0 | Modelo S1 | Mejora | Lectura de negocio |
|---|---:|---:|---:|---|
| Coste anual | 520.345,63€ | 234.659,08 € | 285.686,55€ | Ahorro anual de la carga flexible |
| Ahorro relativo | - | - | 54,90% | Reducción del coste frente a la operación actual |

## 6. Valor de negocio

La optimización permite transformar el consumo eléctrico flexible en una decisión operativa basada en datos. En lugar de mantener una programación fija, la planta puede adaptar diariamente la distribución de su carga flexible utilizando los precios publicados para el día siguiente.

### Recomendación

Se recomienda programar diariamente la carga flexible una vez publicados los precios del mercado diario, asignando el consumo a las horas de menor coste dentro de las restricciones operativas definidas.

Esta decisión permite reducir el coste asociado a la carga flexible sin modificar el volumen total de energía consumida.

### Supuestos
| Supuesto | Valor | Fuente o justificación | Impacto si no se cumple |
|---|---|---|---|
| Consumo flexible diario | 30 MWh/día | Ficha del caso | El ahorro estimado variaría proporcionalmente |
| Potencia máxima flexible | 7 MWh/h | Ficha del caso | Cambiaría la programación óptima |
| Operación actual S0 | 2,5 MWh/h entre las 08:00 y las 20:00 | Ficha del caso | Cambiaría el baseline utilizado para la comparación | 
| Programación posterior a la casación | Sí | Funcionamiento del mercado diario | Sería necesaria una previsión de precios |
| Tratamiento de precios negativos | Sustitución por 0 para el cálculo | Decisión metodológica del equipo | Modificaría parcialmente los costes estimados |

### Impacto cuantificado

| KPI | Valor |
|---|---:|
| Coste anual S0 | 520.345,63€ |
| Coste anual S1 | 234.659,08€ |
| Ahorro anual | 285.686,55€ |
| Ahorro relativo | 54,90% |

## 7. Limitaciones

La solución actual representa una primera aproximación al problema de optimización de la carga flexible y presenta las siguientes limitaciones:

- El análisis utiliza el precio del mercado diario, que no representa por sí solo el coste final completo de la factura eléctrica.
- El modelo considera únicamente la carga flexible definida en el caso y no incorpora restricciones operativas específicas de una planta real.
- El criterio principal de optimización es el coste económico; no se optimizan simultáneamente variables como emisiones o sostenibilidad.
- Si una hora no dispone de las cuatro observaciones cuartohorarias necesarias, se considera incompleta y queda excluida de la asignación de energía en S1. Por tanto, la disponibilidad de horas candidatas para la optimización depende de la completitud de los datos.
- Los precios negativos se sustituyen por cero. Con precios negativos reales el ahorro estimado sería superior, de modo que la decisión es conservadora.
- Los resultados dependen de la calidad y disponibilidad de los datos abiertos utilizados.

### Siguientes pasos

- Incorporar previsión de precios mediante inteligencia artificial para escenarios en los que la decisión deba tomarse antes de publicar los precios del día siguiente.
- Incorporar restricciones operativas reales de la planta mediante programación lineal con PuLP.
- Optimizar simultáneamente coste y emisiones.

## 8. Ejecución y uso de IA

Estas instrucciones permiten ejecutar el proyecto de principio a fin en una instancia EC2 con acceso a un bucket S3. **Los comandos se copian y pegan de uno en uno**, esperando a que termine cada uno antes de lanzar el siguiente.

### 8.1. Requisitos previos

Antes de empezar, hay que disponer de:

- **Acceso a la consola de AWS** con permisos para entrar en una instancia EC2 mediante Session Manager.
- **Una instancia EC2 encendida**, con un rol IAM que permita leer y escribir en el bucket S3 (prefijos `raw/`, `processed/` y `outputs/`). El acceso a AWS se realiza con este rol: no hay que configurar claves de acceso en el repositorio.
- **Un bucket S3 propio** (si se quiere guardar los resultados en S3).
- **Python 3.10 o superior.** En Amazon Linux 2023, el comando `python3` es la versión 3.9, que no vale. Hay que usar `python3.11` (se comprueba en el apartado 8.3).
- **Git** y **AWS CLI**, que vienen instalados en Amazon Linux 2023.
- **Una clave gratuita de AEMET OpenData**, necesaria solo para descargar los datos meteorológicos. Se solicita en <https://opendata.aemet.es/centrodedescargas/inicio>, indicando un correo electrónico; la clave llega por correo en pocos minutos. Es una cadena larga de letras y números que se copia entera, sin espacios.

### 8.2. Acceder a la instancia EC2

1. Abre en el navegador la consola de AWS: <https://console.aws.amazon.com> e inicia sesión con el acceso corporativo.
2. Arriba a la derecha, comprueba que la **región** es  `Europe (Stockholm) eu-north-1`. Si no, despliega el selector de región y elígela.
3. En el buscador de la parte superior escribe **EC2** y entra en el servicio. En el menú de la izquierda, pulsa **Instances**.
4. Marca la casilla de la instancia con ID i-0170d4ea157c887d5.
5. Mira la columna **Instance state**:
   - Si pone **Running**, está encendida y puedes continuar.
   - Si pone **Stopped**, pulsa **Instance state** (arriba a la derecha) → **Start instance**. Espera 1 o 2 minutos hasta que ponga **Running** y los *Status checks* indiquen *2/2 checks passed*.
6. Con la instancia marcada, pulsa **Connect** (botón naranja arriba).
7. Abre la pestaña **Session Manager** y pulsa **Connect**. Se abre la terminal de la instancia. Todos los comandos siguientes se ejecutan ahí.
8. Si el botón **Connect** de Session Manager aparece deshabilitado, la instancia no está registrada en Systems Manager. Espera un par de minutos y recarga la página; si sigue igual, hay que revisar que el rol de la instancia incluya la política `AmazonSSMManagedInstanceCore`.

### 8.3. Clonar el repositorio y preparar el entorno

**Paso 1. Comprobar las versiones instaladas:**

```bash
python3.11 --version
git --version
```

Debe aparecer `Python 3.11.x` y la versión de Git. Si `python3.11` no se encuentra, instálalo (requiere permisos de administrador):

```bash
sudo dnf install -y python3.11
```

**Paso 2. Ir a la carpeta de inicio y clonar el repositorio:**

```bash
cd ~
git clone https://github.com/clauaccenture/odb-challenge-energy-optimizer.git
```

Si la terminal responde `destination path ... already exists`, ya existe una carpeta con ese nombre. Clónalo en una carpeta nueva añadiendo un nombre al final del comando, por ejemplo `... odb-challenge-energy-optimizer.git proyecto_energia`, y usa ese nombre en lugar de `odb-challenge-energy-optimizer` en los pasos siguientes.

**Paso 3. Entrar en la carpeta del proyecto y comprobar su contenido:**

```bash
cd odb-challenge-energy-optimizer
ls -a
ls notebooks
```

Deben aparecer, entre otros, `.env.example`, `requirements.txt`, la carpeta `app` y, dentro de `notebooks`, estos siete scripts: `01_ingesta_aemet.py`, `01_ingesta_redata.py`, `02_calidad_aemet.py`, `02_calidad_redata.py`, `03_gold_aemet.py`, `03_gold_redata.py` y `04_analisis_temperatura_precio.py`.

**Paso 4. Crear el entorno virtual con Python 3.11 y activarlo:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python --version
```

El prompt debe empezar por `(.venv)` y `python --version` debe mostrar `Python 3.11.x`. Mientras dure la sesión, el entorno sigue activo. Si se cierra la terminal, hay que volver a ejecutar `source .venv/bin/activate` desde la carpeta del proyecto.

**Paso 5. Instalar las dependencias** (tarda 1 o 2 minutos):

```bash
pip install -r requirements.txt
```

Termina con una línea `Successfully installed ...`. Un aviso final que dice que hay una versión más reciente de `pip` es solo informativo y puede ignorarse.

### 8.4. Configurar las variables de entorno

El repositorio incluye un fichero de plantilla, `.env.example`, con los nombres de las variables y sin valores. Los pasos son:

**Paso 1. Crear el fichero `.env` a partir de la plantilla:**

```bash
cp .env.example .env
```

**Paso 2. Abrirlo con el editor `nano`:**

```bash
nano .env
```

**Paso 3. Rellenar los valores.** Mueve el cursor con las flechas del teclado y escribe a continuación del signo `=` de cada línea, sin comillas ni espacios:

```env
AEMET_API_KEY=<clave_de_AEMET_recibida_por_correo>
S3_BUCKET=<nombre_de_tu_bucket_s3>
AWS_DEFAULT_REGION=<región_del_bucket>
```

| Variable | Qué poner |
|---|---|
| `AEMET_API_KEY` | La clave de AEMET (apartado 8.1). |
| `S3_BUCKET` | El nombre del bucket, solo el nombre (sin `s3://`). **Si está definido, los scripts suben a S3 todo lo que generan.** Usa un bucket propio para no sobrescribir datos de otros equipos. Para trabajar solo en local, déjalo vacío. |
| `AWS_DEFAULT_REGION` | La región del bucket, por ejemplo `eu-north-1`. |

**Paso 4. Guardar y salir de `nano`:** pulsa `Ctrl+O`, luego Enter para confirmar el nombre, y por último `Ctrl+X`.

**Paso 5. Comprobar que se ha guardado bien:**

```bash
cat .env
```

El fichero `.env` está incluido en `.gitignore`: nunca se sube al repositorio, y no debe compartirse.

**Paso 6 (opcional, solo si se usa S3). Comprobar el acceso a AWS y al bucket:**

```bash
aws sts get-caller-identity
aws s3 ls s3://<nombre_de_tu_bucket_s3>/
```

El primer comando muestra la identidad con la que trabaja la instancia (su rol IAM). El segundo lista el contenido del bucket; si está vacío no muestra nada, y si da `AccessDenied` el rol de la instancia no tiene permisos sobre ese bucket.

**Ejecución solo en local.** Si se deja `S3_BUCKET` vacío, hay que añadir `--no-s3` al final de cada script del pipeline (apartado 8.6). Los resultados quedan entonces únicamente en la carpeta `data/` de la instancia.

### 8.5. Organización de los datos

El pipeline organiza los datos en tres capas. Cada script guarda su resultado en una carpeta local y, si hay bucket definido, también en su prefijo de S3:

| Capa | Carpeta local | Prefijo en S3 |
|---|---|---|
| Bronze (raw) | `data/raw/redata/`, `data/raw/aemet/` | `raw/redata/`, `raw/aemet/` |
| Silver (processed) | `data/processed/redata/`, `data/processed/aemet/` | `processed/redata/`, `processed/aemet/` |
| Gold (outputs) | `data/outputs/redata/`, `data/outputs/aemet/` | `outputs/redata/`, `outputs/aemet/` |

La carpeta `data/` es una caché local: se crea sola al ejecutar los scripts y no se versiona (está en `.gitignore`).

### 8.6. Ejecutar el pipeline

Los scripts están en `notebooks/` y **deben ejecutarse en este orden**, porque cada uno usa los resultados del anterior. Hay que lanzarlos **desde la carpeta del proyecto y con el entorno activado** (el prompt empieza por `(.venv)`), copiando los comandos de uno en uno y esperando a que cada uno termine antes de lanzar el siguiente.

| Paso | Script | Qué hace | Resultado |
|---|---|---|---|
| 1 | `01_ingesta_redata.py` | Descarga los precios del mercado diario (REData) | `data/raw/redata/` (365 ficheros, uno por día) |
| 2 | `01_ingesta_aemet.py` | Descarga las temperaturas diarias (AEMET) | `data/raw/aemet/` (tramos de 15 días) |
| 3 | `02_calidad_redata.py` | Limpia los precios y los pasa a resolución horaria | `data/processed/redata/` |
| 4 | `02_calidad_aemet.py` | Limpia las temperaturas | `data/processed/aemet/` |
| 5 | `03_gold_redata.py` | Calcula S0, S1 y el ahorro | `data/outputs/redata/` (`gold_plan_mensual.parquet` y `gold_programacion_horaria.parquet`) |
| 6 | `03_gold_aemet.py` | Resume la temperatura nacional por día | `data/outputs/aemet/` (`gold_temperatura_diaria.parquet`) |
| 7 | `04_analisis_temperatura_precio.py` | Cruza temperatura y precio | `data/outputs/aemet/` (analisis_temperatura_precio.parquet y gráfico del análisis) |

Los pasos 1 a 6 incluyen `--no-s3`, por lo que guardan los resultados únicamente en la carpeta local `data/`. Para subir también esos resultados a S3, define `S3_BUCKET` en el `.env` (apartado 8.4) y quita `--no-s3` de los comandos que admiten esta opción. El paso 7 se ejecuta sin `--no-s3`.

**Paso 1. Ingesta de REData.** Tarda entre 10 y 15 minutos. Se lanza en segundo plano para que no se interrumpa si se cierra la sesión:

```bash
nohup python -u notebooks/01_ingesta_redata.py --start 2025-10-01 --end 2026-09-30 --no-s3 > ingesta_redata.log 2>&1 &
```

Para ver el avance (sale con `Ctrl+C` sin detener la descarga):

```bash
tail -f ingesta_redata.log
```

Cuando termine, comprueba el resultado:

```bash
tail -n 5 ingesta_redata.log
ls data/raw/redata/precios_*.json | wc -l
```

La última línea del log debe indicar `fallidos: 0` y el recuento debe ser **365**. Si algún día falla, repite el mismo comando: solo descarga los que faltan.

**Paso 2. Ingesta de AEMET** (requiere `AEMET_API_KEY` en el `.env`):

```bash
python notebooks/01_ingesta_aemet.py --start 2025-10-01 --end 2026-09-30 --no-s3
ls data/raw/aemet/aemet_*.json | wc -l
```

El recuento debe ser **25** ficheros (tramos de 15 días). Si falla un tramo, hay que repetir el comando completo.

**Paso 3. Calidad de REData:**

```bash
python notebooks/02_calidad_redata.py --no-s3
```

Muestra un informe. Debe indicar `rows_read` 35040, `hours_output` 8760, `days_total` 365 y `negative_prices_replaced_by_0` 2803.

**Paso 4. Calidad de AEMET:**

```bash
python notebooks/02_calidad_aemet.py --no-s3
```

Termina con la línea `Silver histórico completo: 29**** registros. Guardado data/processed/aemet/aemet_diario.json`.

**Paso 5. Gold de REData** (optimización diaria de S0 frente a S1):

```bash
python notebooks/03_gold_redata.py --no-s3
```

Debe mostrar `Dias: 365 (optimos: 365)` y `Ahorro total: 285686.55 EUR | ahorro ponderado: 54.90 %`.

**Paso 6. Gold de AEMET:**

```bash
python notebooks/03_gold_aemet.py --no-s3
```

Termina con la línea `Guardado data/outputs/aemet/gold_temperatura_diaria.parquet`.

**Paso 7. Análisis de temperatura y precio:**

```bash
python notebooks/04_analisis_temperatura_precio.py
```

**Comprobación final.** Lista los resultados generados:

```bash
ls -lh data/outputs/redata/ data/outputs/aemet/
```

Para ejecutar el proyecto con **otro periodo**, basta con cambiar las fechas `--start` y `--end` de los pasos 1 y 2. Los valores esperados anteriores corresponden al periodo del 01/10/2025 al 30/09/2026.

### 8.7. Dashboard Streamlit (opcional)

El proyecto incluye un dashboard desarrollado con Streamlit. Es una capa de
visualización y no es necesaria para ejecutar el pipeline ni para obtener los
resultados del análisis. Lee las tablas Gold publicadas en S3; el bucket se
define en `app/data_loader.py` y, si se usa otro, hay que editarlo allí.
La configuración y ejecución en un entorno propio están en `app/README.md`.

**Acceso al frontend para la evaluación:** No es necesario repetir el pipeline para consultar los resultados ya publicados en S3. Se ha preparado un script de arranque en la EC2 y se entrega un `.bat` para abrir el túnel desde Windows. Se requiere acceso corporativo a la cuenta AWS del proyecto, permisos de Session Manager y de apertura del túnel, y AWS CLI 2.32.0 o posterior y Session Manager Plugin instalados en el PC.

1. En AWS, seleccionar **Estocolmo (`eu-north-1`)** y la instancia cuyo ID figura en el `.bat`. Si está detenida, iniciarla con los permisos correspondientes y esperar a que esté disponible en Session Manager.
2. Abrir **Conectar → Session Manager** y, si Streamlit no está ya arrancado, ejecutar:

   ```bash
   bash /home/ssm-user/energy-optimizer-s3-test/iniciar_frontend.sh
   ```

3. En Windows, ejecutar el `.bat` entregado, autorizar el inicio de sesión en la cuenta y rol del proyecto si se solicita y, cuando indique que el túnel está abierto, acceder a **http://localhost:18501**.

Mantener abiertas la consola de Streamlit y la ventana del túnel. Al terminar, cerrar el túnel con `Ctrl+C` y detener Streamlit solo si nadie más lo utiliza. No es necesario abrir puertos a Internet, instalar Python en el PC ni actualizar el código de la instancia.

### 8.8. Uso de IA generativa

Se ha utilizado el asistente de IA Copilot, mediante una cuenta autorizada por la organización, como apoyo en: revisión y depuración del código de los scripts, redacción y revisión del README y de la guía de ejecución, apoyo en la demo de Streamlit. No se ha compartido información confidencial: todos los datos utilizados son abiertos. El código y los resultados generados con ayuda de la IA han sido revisados y verificados por el equipo, y cualquier miembro puede explicar cualquier parte del código y del análisis.
