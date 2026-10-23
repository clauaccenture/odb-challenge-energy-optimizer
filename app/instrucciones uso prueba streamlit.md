# Instrucciones de uso y prueba de Streamlit

Guía interna para abrir la app de EC2 desde un PC Windows mediante un túnel SSM.

## Antes de empezar

- La EC2 está encendida en **Estocolmo (`eu-north-1`)**.
- El repositorio ya está en `/home/ssm-user/energy-optimizer-s3-test`, en la rama **`develop`**.
- Python 3.11, el entorno `.venv` y las dependencias ya están instalados en EC2.
- La app adaptada al contrato actual lee `gold_plan_mensual.parquet` y `gold_programacion_horaria.parquet` desde `s3://energy-optimizer-grupo4/outputs/redata/`. Antes de probar, comprobar que esta adaptación esté integrada en `develop` y desplegada en EC2. No hay que descargar los datos al PC.
- Cada persona necesita acceso corporativo AWS y permisos para iniciar sesiones SSM y usar `AWS-StartPortForwardingSession`.

**Una persona arranca Streamlit en la EC2 compartida; cada compañero abre su propio túnel en su PC.** Si Streamlit ya está funcionando, no arrancar otra copia ni actualizar el código sin avisar.

Esta guía está versionada en el repositorio para compartirla con el equipo. No incluir claves, tokens ni códigos de autorización. Es una guía de pruebas, no un despliegue de producción.

## 1. PC Windows: instalar las herramientas una sola vez

Abrir **PowerShell en el PC**, no en EC2:

```powershell
winget install --id Amazon.AWSCLI --exact --source winget
winget install --id Amazon.SessionManagerPlugin --exact --source winget
```

Aceptar los permisos solo si se está autorizado. Si la instalación corporativa está bloqueada, consultar al soporte.

Abrir una nueva ventana de PowerShell y comprobar:

```powershell
aws --version
session-manager-plugin --version
```

Si ya están instaladas, saltar la instalación. Si no se reconocen, reiniciar PowerShell o VS Code completo. `aws login` requiere AWS CLI 2.32.0 o posterior; para actualizar una instalación antigua:

```powershell
winget upgrade --id Amazon.AWSCLI --exact --source winget
```

No hace falta instalar Python ni Streamlit en el PC.

## 2. PC Windows: iniciar sesión en AWS

1. Entrar en la consola AWS mediante la aplicación del portal corporativo Microsoft My Apps.
2. Mantener esa sesión abierta en el navegador predeterminado.
3. En PowerShell local, ejecutar:

```powershell
aws login --profile energy-optimizer --region eu-north-1
```

Se abre el navegador: seleccionar la cuenta y el rol del proyecto y autorizar la solicitud.

Comprobar:

```powershell
aws sts get-caller-identity --profile energy-optimizer --region eu-north-1
```

Debe devolver la identidad esperada. No compartir la salida completa ni códigos de acceso. Si aparece `AccessDenied` o se exige otro método corporativo, consultar al administrador; no crear claves para evitarlo.

## 3. EC2: actualizar y arrancar la app

### Prueba temporal de la adaptación REData antes de fusionarla

La adaptación a los dos nuevos Parquet se prueba desde `feature_connect_s3_bucket` hasta que se fusione en `develop`. Avisar al equipo y detener la app con Ctrl+C en su consola antes de cambiar la rama compartida.

En EC2, ejecutar uno por uno:

```bash
cd /home/ssm-user/energy-optimizer-s3-test
git status --short --branch
```

Si hay cambios locales, detenerse sin descartarlos. Si está limpio:

```bash
git fetch origin
git switch feature_connect_s3_bucket
git pull --ff-only origin feature_connect_s3_bucket
git log -1 --oneline
source .venv/bin/activate
python -m unittest discover -s app/tests -v
python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Si cualquier comando falla, no continuar. Abrir el túnel del paso 4 y probar el dashboard del paso 5. Las pruebas automáticas usan S3 simulado; abrir la app comprueba la lectura real de S3. El rol de EC2 necesita `s3:GetObject` sobre `outputs/redata/gold_plan_mensual.parquet` y `outputs/redata/gold_programacion_horaria.parquet`.

El procedimiento que sigue corresponde al despliegue habitual de `develop`, no a esta prueba temporal.

**Solo lo hace una persona.** Si la app ya funciona y está actualizada, pasar al paso 4.

En la consola web AWS:

1. Seleccionar **Estocolmo / `eu-north-1`**.
2. Ir a **EC2 > Instancias** y seleccionar la instancia del proyecto.
3. Copiar su **ID de instancia** (`i-...`): se usará para el túnel.
4. Pulsar **Conectar > Session Manager > Conectar**.

Los siguientes comandos se ejecutan **en la consola Linux de EC2**, uno por uno. Si cualquiera falla, detenerse.

### Comprobar que no hay otra app escuchando

```bash
ss -ltn 'sport = :8501'
```

Si aparece una fila `LISTEN`, coordinar con quien mantiene el servidor. No matar procesos ajenos ni arrancar otra copia.

### Actualizar el repositorio

```bash
cd /home/ssm-user/energy-optimizer-s3-test
git status --short --branch
```

No debe haber archivos modificados. Si los hay, detenerse y consultar; no descartarlos.

```bash
git switch develop
git pull --ff-only origin develop
git log -1 --oneline
```

La conexión S3 y el calendario ya están integrados en `develop`. No utilizar la antigua feature para estas pruebas.

### Activar el entorno y arrancar

```bash
source .venv/bin/activate
python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Cuando aparezca `http://127.0.0.1:8501`, **dejar esta consola abierta**. El navegador del PC todavía necesita el túnel del siguiente paso.

No reinstalar dependencias cada vez. No abrir el puerto 8501 a Internet ni cambiar la dirección de escucha.

## 4. PC Windows: abrir el túnel

En PowerShell local, sustituir `i-TU_INSTANCIA` por el ID real de la EC2 y ejecutar:

```powershell
aws ssm start-session --target i-TU_INSTANCIA --document-name AWS-StartPortForwardingSession --parameters "portNumber=8501,localPortNumber=8501" --profile energy-optimizer --region eu-north-1
```

Esperar al mensaje de puerto abierto o `Waiting for connections`. **Mantener este PowerShell abierto.**

Cada compañero utiliza su propio túnel. No hay que modificar el grupo de seguridad.

## 5. Navegador: abrir y probar

Abrir en el PC:

<http://localhost:8501>

Comprobar:

- Funcionan las vistas de resumen, programación diaria y evolución del ahorro.
- Seleccionar un día cambia su programación y permite descargar el CSV.
- La fecha se conserva al pasar del resumen a la programación diaria.
- El calendario deshabilita los días sin programación válida. Con el Gold actual, en 2026 se pueden seleccionar días hasta el 30 de septiembre, pero no el 1 de octubre ni el 24 de diciembre.
- Los datos actuales cubren del 1 de octubre de 2025 al 30 de septiembre de 2026: 365 días óptimos y 8.760 horas.

La caché dura cinco minutos. Si se actualiza Gold, pulsar **Actualizar datos de S3** solo después de completar la subida de ambos Parquet. Los recuentos y fechas pueden cambiar si cambia Gold.

## 6. Al terminar

1. Cada persona cierra su túnel con **Ctrl+C en PowerShell local**.
2. Puede cerrar su sesión AWS CLI:

```powershell
aws logout --profile energy-optimizer
```

3. Cuando todos terminen, quien arrancó Streamlit lo detiene con **Ctrl+C en su consola EC2**.
4. En esa consola, comprobar y salir:

```bash
ss -ltn 'sport = :8501'
```

No debe aparecer ninguna fila `LISTEN`. Después:

```bash
deactivate
exit
```

La EC2 queda encendida; no apagarla ni reiniciarla sin coordinarlo. La sesión web AWS es independiente del login de PowerShell. Bloquear el PC al ausentarse.

## Ayuda rápida

- **Sesión AWS expirada:** repetir `aws login --profile energy-optimizer --region eu-north-1`.
- **AccessDenied:** consultar permisos corporativos, SSM o S3 según dónde aparezca. El login del PC abre el túnel; la app usa las credenciales de EC2 para leer S3.
- **TargetNotConnected:** comprobar ID, región y disponibilidad de la instancia en SSM.
- **El túnel abre pero no carga la página:** comprobar que Streamlit sigue funcionando en la instancia correcta.
- **Puerto local ocupado:** usar `localPortNumber=18501` en el comando del túnel y abrir <http://localhost:18501>. Mantener `portNumber=8501`.
- **Pantalla de error:** guardar el mensaje sin secretos y compartirlo con el equipo. No editar Gold para ocultarlo.

## Importante: actualizar EC2 después de modificar la app

**Publicar o fusionar cambios en GitHub NO actualiza automáticamente la EC2.** Hay que actualizar manualmente su `develop` y reiniciar Streamlit.

### Ejemplo: añadir datos Gold de AEMET con `feature_AEMET_Streamlit`

#### A. Desarrollo: en el repositorio del PC de la compañera

Partir de un repositorio sin cambios pendientes y ejecutar uno por uno:

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature_AEMET_Streamlit
```

Implementar la integración de AEMET, verificar el esquema de sus datos Gold y probarla. Si requiere paquetes nuevos, actualizar también `requirements.txt`. Si lee objetos S3 nuevos, comprobar sus rutas y los permisos de lectura de EC2.

Revisar y publicar solo los archivos relacionados con el cambio. Por ejemplo, si se modificaron únicamente estos dos:

```powershell
git diff
git add app/streamlit_app.py app/data_loader.py
git commit -m "Mostrar datos Gold de AEMET en Streamlit"
git push -u origin feature_AEMET_Streamlit
```

Adaptar `git add` a los archivos realmente modificados; incluir `requirements.txt` si cambió. No subir credenciales.

En GitHub, crear una **pull request de `feature_AEMET_Streamlit` hacia `develop`**, revisar los cambios y fusionarla cuando esté validada.

Mientras no se fusione, actualizar `develop` en EC2 no descargará la funcionalidad AEMET.

#### B. Despliegue manual: en la consola SSM de EC2

1. Avisar al equipo y detener Streamlit con **Ctrl+C en la consola que lo está ejecutando**. No cerrar los túneles si se van a reutilizar.
2. Ejecutar uno por uno:

```bash
cd /home/ssm-user/energy-optimizer-s3-test
git status --short --branch
```

Si hay archivos modificados, detenerse y consultar. Si está limpio:

```bash
git switch develop
git pull --ff-only origin develop
git log -1 --oneline
git rev-list --left-right --count HEAD...origin/develop
```

El último comando debe mostrar `0 0`. Comprobar que el historial incluye la integración AEMET; el título del último commit dependerá de cómo se fusione la pull request.

3. Activar el entorno:

```bash
source .venv/bin/activate
```

Solo si cambió `requirements.txt` o faltan dependencias:

```bash
python -m pip install -r requirements.txt
```

Si falla, no continuar hasta resolverlo. No usar `sudo pip`.

4. Arrancar de nuevo:

```bash
python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

5. Mantener la consola abierta, abrir o reutilizar el túnel y recargar <http://localhost:8501>. Comprobar que aparece AEMET y que siguen funcionando los datos energéticos, los filtros y el calendario.

**Resumen: feature en el PC > pruebas > push > pull request y fusión a `develop` > pull manual de `develop` en EC2 > reinicio de Streamlit > comprobación en el navegador.**
