import json
import time
from queue import Queue, Empty

import streamlit as st
from streamlit.components.v1 import html

from mqtt_client import MQTTClient, TOPIC_LIGHTS_CMD, TOPIC_SERVO_CMD

# -----------------------
# Helper para inicializar MQTT (singleton dentro de Streamlit)
# -----------------------
def get_mqtt_client():
    if "mqtt_client" not in st.session_state:
        st.session_state["mqtt_queue"] = Queue()
        client = MQTTClient(queue=st.session_state["mqtt_queue"])
        client.start()
        st.session_state["mqtt_client"] = client
        # estados iniciales
        st.session_state.setdefault("light_state", "unknown")
        st.session_state.setdefault("temps", [])   # lista de (ts, value)
        st.session_state.setdefault("hums", [])
        st.session_state.setdefault("timestamps", [])
        st.session_state.setdefault("security", "No se han detectado intrusos")
        # para depuración: último payload RAW recibido en /lights/state
        st.session_state.setdefault("last_lights_state_raw", None)
    return st.session_state["mqtt_client"]

# Cuando llegue un mensaje MQTT, lo procesamos y actualizamos session_state
def mqtt_message_consumer():
    q = st.session_state.get("mqtt_queue")
    if not q:
        return
    updated = False
    try:
        while True:
            item = q.get_nowait()
            # Soportar tanto 2-tuplas (topic, parsed) como 3-tuplas (topic, parsed, raw)
            if isinstance(item, tuple) and len(item) == 3:
                topic, parsed, raw = item
            elif isinstance(item, tuple) and len(item) == 2:
                topic, parsed = item
                raw = None
            else:
                try:
                    topic = item[0]
                    parsed = item[1] if len(item) > 1 else None
                    raw = item[2] if len(item) > 2 else None
                except Exception:
                    continue

            # Para depuración, si el topic es lights/state almacenamos el raw
            if topic.endswith("/lights/state"):
                if raw is not None:
                    st.session_state["last_lights_state_raw"] = raw
                else:
                    try:
                        st.session_state["last_lights_state_raw"] = json.dumps(parsed, ensure_ascii=False)
                    except Exception:
                        st.session_state["last_lights_state_raw"] = str(parsed)

            # topic checks
            if topic.endswith("/lights/state"):
                # estado luz: solo actualizar si vemos power="on"|"off"
                power = None
                if isinstance(parsed, dict):
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and "power" in data:
                        power = data.get("power")
                    if power is None and "power" in parsed:
                        power = parsed.get("power")
                # heurística sobre raw si no hubo parsed power
                if power is None and raw is not None and '"power"' in raw:
                    try:
                        tmp = json.loads(raw)
                        data = tmp.get("data") or {}
                        if isinstance(data, dict) and "power" in data:
                            power = data.get("power")
                        elif "power" in tmp:
                            power = tmp.get("power")
                    except Exception:
                        pass
                if power is not None:
                    if isinstance(power, str):
                        p = power.lower()
                        if p in ("on", "off"):
                            st.session_state["light_state"] = p
                            updated = True

            elif topic.endswith("/temp/telemetry"):
                # Telemetría DHT22: t/h
                if isinstance(parsed, dict):
                    ts = parsed.get("ts", int(time.time()*1000))
                    data = parsed.get("data", {})
                    t = data.get("temp")
                    h = data.get("hum")
                    # admitir también payloads con claves directas
                    if t is None and isinstance(parsed.get("data"), dict):
                        t = parsed.get("data").get("temp")
                    if h is None and isinstance(parsed.get("data"), dict):
                        h = parsed.get("data").get("hum")
                    if t is not None or h is not None:
                        # si falta una de las variables, toleramos (pero no añadimos None)
                        try:
                            if t is not None:
                                st.session_state["temps"].append(t)
                            if h is not None:
                                st.session_state["hums"].append(h)
                            st.session_state["timestamps"].append(ts)
                            # keep reasonable history
                            max_len = 200
                            st.session_state["timestamps"] = st.session_state["timestamps"][-max_len:]
                            st.session_state["temps"] = st.session_state["temps"][-max_len:]
                            st.session_state["hums"] = st.session_state["hums"][-max_len:]
                            updated = True
                        except Exception:
                            pass
                else:
                    # si parsed no es dict, intentar extraer desde raw si está presente
                    if raw:
                        try:
                            tmp = json.loads(raw)
                            data = tmp.get("data", {})
                            t = data.get("temp")
                            h = data.get("hum")
                            ts = tmp.get("ts", int(time.time()*1000))
                            if t is not None or h is not None:
                                if t is not None:
                                    st.session_state["temps"].append(t)
                                if h is not None:
                                    st.session_state["hums"].append(h)
                                st.session_state["timestamps"].append(ts)
                                max_len = 200
                                st.session_state["timestamps"] = st.session_state["timestamps"][-max_len:]
                                st.session_state["temps"] = st.session_state["temps"][-max_len:]
                                st.session_state["hums"] = st.session_state["hums"][-max_len:]
                                updated = True
                        except Exception:
                            pass

            elif topic.endswith("/security/event"):
                # Hacer parsing tolerante: aceptar data.event, event, data == "motion", o raw conteniendo "motion"
                got_motion = False
                if isinstance(parsed, dict):
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and data.get("event") == "motion":
                        got_motion = True
                    # aceptar parsed direct key 'event'
                    if parsed.get("event") == "motion":
                        got_motion = True
                    # a veces device puede enviar {"data":"motion"} (no ideal) -> cubrirlo
                    if isinstance(data, str) and data == "motion":
                        got_motion = True
                # heurística sobre raw
                if not got_motion and raw and "motion" in raw:
                    got_motion = True
                if got_motion:
                    st.session_state["security"] = "Intruso detectado"
                    updated = True

            elif topic.endswith("/servo/state"):
                # opcional: manejar confirmaciones del servo si necesitas
                pass

    except Empty:
        pass

    if updated:
        # Intentamos forzar rerun; si experimental_rerun no existe, usamos set_query_params para provocar rerun
        try:
            rerun = getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
            else:
                # cambiar un query param provoca rerun en Streamlit
                st.experimental_set_query_params(_refresh=int(time.time()*1000))
        except Exception:
            try:
                st.experimental_set_query_params(_refresh=int(time.time()*1000))
            except Exception:
                pass

# Publica comandos de luz (matching tu .ino)
def publish_light_cmd(client, on_or_off: str):
    payload = {"cmd": "power", "value": on_or_off}
    client.publish_json(TOPIC_LIGHTS_CMD, payload)

def publish_servo_cmd(client, angle: int):
    payload = {"angle": angle}
    client.publish_json(TOPIC_SERVO_CMD, payload)

# -----------------------
# Interfaz Streamlit
# -----------------------
st.set_page_config(page_title="ESP32 — Control y Monitor", layout="wide")

st.title("ESP32 — Interfaz Streamlit (MQTT + Voz)")

# Inicializa MQTT
client = get_mqtt_client()

# Procesa mensajes entrantes (no tocar; esto actualiza session_state si hay mensajes en la cola)
mqtt_message_consumer()

# Intentar sincronizar light_state desde last_lights_state_raw (si existe)
last_raw = st.session_state.get("last_lights_state_raw")
if last_raw:
    try:
        parsed_last = json.loads(last_raw)
        data = parsed_last.get("data") if isinstance(parsed_last, dict) else {}
        power = None
        if isinstance(data, dict) and "power" in data:
            power = data.get("power")
        elif isinstance(parsed_last, dict) and "power" in parsed_last:
            power = parsed_last.get("power")
        if power and isinstance(power, str):
            p = power.lower()
            if p in ("on", "off"):
                st.session_state["light_state"] = p
    except Exception:
        pass

# Sidebar: selector de páginas
page = st.sidebar.selectbox("Páginas", ["Luz", "Sensores", "Seguridad"])

# --- PÁGINA LUZ ---
if page == "Luz":
    st.header("Control de luz (voz)")
    st.write("Usa los botones o el reconocimiento por voz. Di 'Encender' o 'Apagar'.")

    col1, col2 = st.columns([1, 3])

    # Botón ON: publicamos y actualizamos el raw esperado inmediatamente
    with col1:
        if st.button("Activar LED (enviar ON)"):
            publish_light_cmd(client, "on")
            st.session_state["light_state"] = "on"
            st.session_state["last_lights_state_raw"] = json.dumps({
                "ts": int(time.time() * 1000),
                "device": "esp32-01",
                "data": {"power": "on"}
            }, ensure_ascii=False)
            st.success("Comando enviado: encender")

    # Botón OFF
    with col2:
        if st.button("Desactivar LED (enviar OFF)"):
            publish_light_cmd(client, "off")
            st.session_state["light_state"] = "off"
            st.session_state["last_lights_state_raw"] = json.dumps({
                "ts": int(time.time() * 1000),
                "device": "esp32-01",
                "data": {"power": "off"}
            }, ensure_ascii=False)
            st.success("Comando enviado: apagar")

    st.write("---")
    st.write("Reconocimiento por voz (Web Speech API). Pulsa 'Iniciar reconocimiento' y habla en español (Chrome/Edge recom.)")

    # --- (NO toqué nada del componente de voz) ---
    # Si estás usando Bokeh o el iframe fallback, el código de voz permanece intacto en tu app.
    # ... (el componente de voz existente continúa aquí en tu app) ...

    # Mostrar estado después de botones/voz
    st.write("Estado actual de la luz:")
    light_state = st.session_state.get("light_state", "unknown")
    if light_state == "on":
        st.success("La luz está ENCENDIDA")
    elif light_state == "off":
        st.info("La luz está APAGADA")
    else:
        st.write("Estado desconocido (esperando mensaje retained del dispositivo).")

    # Mostrar payload RAW más reciente (depuración)
    st.write("Último payload recibido en /lights/state (raw):")
    st.code(st.session_state.get("last_lights_state_raw", "— no recibido —"))

# --- PÁGINA SENSORES ---
elif page == "Sensores":
    st.header("Temperatura y Humedad (DHT22)")
    st.write("Gráficas en tiempo real (últimos valores recibidos).")

    # Auto-refresh pequeño: componente HTML que hace postMessage cada 2s para forzar rerun
    # Esto permite que mqtt_message_consumer() se ejecute periódicamente y actualice la UI.
    html(
        """
        <script>
        if (!window._streamlit_autorefresh_sensors) {
            window._streamlit_autorefresh_sensors = true;
            setInterval(function(){
                window.parent.postMessage({isStreamlitMessage:true, component:'autorefresh_sensors', ts: Date.now()}, "*");
            }, 2000);
        }
        </script>
        """,
        height=0,
    )

    temps = st.session_state.get("temps", [])
    hums = st.session_state.get("hums", [])
    timestamps = st.session_state.get("timestamps", [])

    import pandas as pd
    if timestamps and temps and hums:
        idx = pd.to_datetime([ts/1000.0 for ts in timestamps], unit='s')
        df = pd.DataFrame({"temperatura": temps, "humedad": hums}, index=idx)
        st.line_chart(df["temperatura"], height=250, width='stretch')
        st.line_chart(df["humedad"], height=250, width='stretch')
    else:
        st.write("No hay datos de temperatura/humedad todavía. Esperando telemetría desde el ESP32.")

    st.write("---")
    st.write("Control manual del servo desde esta página (al activarlo, moverá el servo a 90°).")
    if st.button("Activar servo (90°)"):
        publish_servo_cmd(client, 90)
        st.success("Comando servo enviado: 90°")

# --- PÁGINA SEGURIDAD ---
elif page == "Seguridad":
    st.header("Seguridad / PIR")
    st.write("Cuando el sensor PIR se active (evento 'motion'), esta página cambiará a 'Intruso detectado' automáticamente.")

    # Auto-refresh también en la página de seguridad para que el evento aparezca sin tener que recargar
    html(
        """
        <script>
        if (!window._streamlit_autorefresh_security) {
            window._streamlit_autorefresh_security = true;
            setInterval(function(){
                window.parent.postMessage({isStreamlitMessage:true, component:'autorefresh_security', ts: Date.now()}, "*");
            }, 1500);
        }
        </script>
        """,
        height=0,
    )

    status = st.session_state.get("security", "No se han detectado intrusos")
    if status == "Intruso detectado":
        st.error(status)
    else:
        st.success(status)

    st.write("---")
    st.write("Comando de voz para seguridad: di 'seguridad' para mover el servo a 110°.")
    # (componente de voz intacto en tu app)
    # si el componente de voz devuelve texto, el handler existente seguirá publicando el comando al servo.

# Footer / información de conexión MQTT
st.sidebar.write("MQTT broker:")
client = get_mqtt_client()
st.sidebar.write(f"{client.broker}:{client.port}")
st.sidebar.write("Último client id (si disponible):")
try:
    cid = client.client._client_id.decode() if hasattr(client.client, '_client_id') else ""
except Exception:
    cid = ""
st.sidebar.write(cid)
st.sidebar.write("Último payload /lights/state (raw):")
st.sidebar.write(st.session_state.get("last_lights_state_raw", "— no recibido —"))
