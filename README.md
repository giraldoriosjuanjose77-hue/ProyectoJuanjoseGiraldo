# Proyecto Streamlit + ESP32 (MQTT) — Control y Monitorización

Este repositorio contiene una aplicación Streamlit que se comunica por MQTT con tu ESP32 (Wokwi) para:

- Controlar el LED (encender / apagar) vía reconocimiento de voz.
- Mostrar gráficas en tiempo real de temperatura y humedad (DHT22).
- Monitorizar el sensor PIR y mostrar alerta "Intruso detectado" en tiempo real.
- Controlar un servo (página de sensores y página de seguridad — distintos ángulos).

He adaptado los topics y el comportamiento al código .ino que compartiste (BASE_TOPIC = `giraldoriosjuanjose77-hue`) para que la app publique/subscriba a los mismos topics MQTT que tu ESP32.

IMPORTANTE: la aplicación usa el micrófono del navegador mediante la Web Speech API (API de reconocimiento de voz en el navegador). Por eso:
- Debes abrir la app en un navegador que soporte la Web Speech API (Chrome en escritorio funciona bien).
- Cuando la app solicite permiso para el micrófono, acéptalo.
- Para desplegar en Streamlit Cloud, ese servicio también abrirá la app en un navegador y pedirá permisos.

Contenido:
- app.py — aplicación Streamlit (una sola aplicación con selector de páginas).
- mqtt_client.py — cliente MQTT (paho-mqtt), maneja suscripciones y actualiza estado.
- speech_component.html — pequeño componente HTML/JS embebido desde Streamlit para reconocimiento de voz (usa Web Speech API).
- requirements.txt — dependencias Python.
- .streamlit/config.toml — configuración recomendada para Streamlit Cloud.

Cómo usar (rápido)
1. Crea un repo en Github y sube estos archivos (más abajo están los comandos git sugeridos).
2. En tu máquina o en Streamlit Cloud instala dependencias:
   pip install -r requirements.txt
3. Ejecuta localmente:
   streamlit run app.py
4. Abre la URL que Streamlit muestre (normalmente http://localhost:8501).
5. Conecta tu Wokwi/ESP32 al broker MQTT (en el .ino usas test.mosquitto.org). La app también se conecta al mismo broker por defecto.
6. Prueba las páginas:
   - Página "Luz": botón para iniciar reconocimiento; di "Encender" o "Apagar".
   - Página "Sensores": verás las gráficas de temperatura y humedad en tiempo real; botón "Activar servo (90°)" para mover servo a 90°.
   - Página "Seguridad": texto de estado (No se han detectado intrusos / Intruso detectado). Botón de reconocimiento: di "seguridad" para mover servo 110°.

Notas técnicas y permisos
- El reconocimiento de voz lo realiza el navegador (Web Speech API). No requiere claves externas.
- La app usa paho-mqtt para conectarse al broker y suscribirse a los topics que publica tu ESP32.
- Para que las gráficas y estado se actualicen en "tiempo real" la app mantiene una conexión MQTT en background (hilo) y guarda datos en `st.session_state`. La actualización en la interfaz se hace con `st.experimental_rerun()` en puntos controlados.
- Si despliegas en Streamlit Cloud, recuerda vincular el repo y desplegar la app desde allí. Cuando la app pida permisos de micrófono, acepta.

Comandos sugeridos para crear el repo local y subir a GitHub
(ajusta `origin` por la URL de tu repo en GitHub):

git init
git add .
git commit -m "Initial commit — Streamlit app MQTT + voice"
git branch -M main
git remote add origin https://github.com/<TU-USER>/<TU-REPO>.git
git push -u origin main

Deploy en Streamlit Cloud
- Ve a https://streamlit.io/cloud y conecta tu cuenta GitHub.
- Crea una nueva app seleccionando el repo y la rama `main`.
- Streamlit Cloud instalará las dependencias y desplegará. Abre la URL y acepta permisos de micrófono.

Si quieres que yo cree el repositorio y haga el push, dime el nombre del repo y dame permisos o dame instrucciones (no tengo acceso directo a tu GitHub desde aquí).

Última observación
He incluido archivos con todo el código necesario. Si quieres, puedo:
- Ajustar el broker MQTT (si no quieres usar test.mosquitto.org).
- Configurar autenticación MQTT (usuario/clave, TLS).
- Crear el repo en GitHub si me proporcionas acceso (o guío paso a paso).

Ahora te dejo los archivos principales del proyecto.
