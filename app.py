# app.py
import json
import threading
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
                # formato inesperado: intentar extraer topic/raw
                try:
                    topic = item[0]
                    parsed = item[1] if len(item) > 1 else None
                    raw = item[2] if len(item) > 2 else None
                except Exception:
                    # saltar este item si no podemos entenderlo
                    continue

            # Para depuración, si el topic es lights/state almacenamos el raw
            if topic.endswith("/lights/state"):
                if raw is not None:
                    st.session_state["last_lights_state_raw"] = raw
                else:
                    # si no hay raw, intentar reconstruir del parsed
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
                    # si power no es string o no es on/off, lo ignoramos (lo dejamos para depuración)

            elif topic.endswith("/temp/telemetry"):
                if isinstance(parsed, dict):
                    ts = parsed.get("ts", int(time.time()*1000))
                    data = parsed.get("data", {})
                    t = data.get("temp")
                    h = data.get("hum")
                    if t is not None and h is not None:
                        st.session_state["timestamps"].append(ts)
                        st.session_state["temps"].append(t)
                        st.session_state["hums"].append(h)
                        max_len = 200
                        st.session_state["timestamps"] = st.session_state["timestamps"][-max_len:]
                        st.session_state["temps"] = st.session_state["temps"][-max_len:]
                        st.session_state["hums"] = st.session_state["hums"][-max_len:]
                        updated = True

            elif topic.endswith("/security/event"):
                if isinstance(parsed, dict):
                    data = parsed.get("data", {})
                    event = data.get("event")
                    if event == "motion":
                        st.session_state["security"] = "Intruso detectado"
                        updated = True

            elif topic.endswith("/servo/state"):
                # opcional: manejar confirmaciones del servo
                pass

    except Empty:
        pass

    if updated:
        # Intentamos forzar rerun si la función existe; si no, no fallamos
        try:
            # experimental_rerun puede no estar presente en algunos entornos
            rerun = getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
        except Exception:
            # no bloqueamos la app si rerun falla
            pass

# Publica comandos de luz (matching tu .ino)
def publish_light_cmd(client, on_or_off: str):
    payload = {"cmd": "power", "value": on_or_off}
    client.publish_json(TOPIC_LIGHTS_CMD, payload)

def publish_servo_cmd(client, angle: int):
    payload = {"angle": angle}
    client.publish_json(TOPIC_SERVO_CMD, payload)

# Componente HTML para reconocimiento de voz
def voice_recognition_component(key="voice"):
    with open("speech_component.html", "r", encoding="utf-8") as f:
        content = f.read()
    value = html(content, height=160)
    return value

# -----------------------
# Interfaz Streamlit
# -----------------------
st.set_page_config(page_title="ESP32 — Control y Monitor", layout="wide")

st.title("ESP32 — Interfaz Streamlit (MQTT + Voz)")

# Inicializa MQTT
client = get_mqtt_client()

# Consume mensajes en cola (non-blocking)
mqtt_message_consumer()

# Sidebar: selector de páginas
page = st.sidebar.selectbox("Páginas", ["Luz", "Sensores", "Seguridad"])

if page == "Luz":
    st.header("Control de luz (voz)")
    st.write("Estado actual de la luz:")
    light_state = st.session_state.get("light_state", "unknown")
    if light_state == "on":
        st.success("La luz está ENCENDIDA")
    elif light_state == "off":
        st.info("La luz está APAGADA")
    else:
        st.write("Estado desconocido (esperando mensaje retained del dispositivo).")

    st.write("Usa el botón abajo para comenzar el reconocimiento por voz. Di 'Encender' o 'Apagar'.")
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Activar LED (enviar ON)"):
            publish_light_cmd(client, "on")
            st.session_state["light_state"] = "on"   # feedback inmediato
            st.success("Comando enviado: encender")
    with col2:
        if st.button("Desactivar LED (enviar OFF)"):
            publish_light_cmd(client, "off")
            st.session_state["light_state"] = "off"  # feedback inmediato
            st.success("Comando enviado: apagar")

    st.write("---")
    st.write("Reconocimiento de voz (Web Speech API). Pulsa 'Iniciar reconocimiento' en el componente que aparece y habla.")
    value = voice_recognition_component(key="voice_luz")
    if value and isinstance(value, dict) and value.get("text"):
        txt = value.get("text", "").lower()
        st.write("Reconocido:", txt)
        if "encender" in txt:
            publish_light_cmd(client, "on")
            st.session_state["light_state"] = "on"
            st.success("Comando enviado: encender")
        elif "apagar" in txt:
            publish_light_cmd(client, "off")
            st.session_state["light_state"] = "off"
            st.success("Comando enviado: apagar")
        else:
            st.warning("No se reconoció 'encender' ni 'apagar' en el texto.")

    # Mostrar payload RAW más reciente (depuración)
    st.write("Último payload recibido en /lights/state (raw):")
    st.code(st.session_state.get("last_lights_state_raw", "— no recibido —"))

elif page == "Sensores":
    st.header("Temperatura y Humedad (DHT22)")
    st.write("Gráficas en tiempo real (últimos valores recibidos).")
    temps = st.session_state.get("temps", [])
    hums = st.session_state.get("hums", [])
    timestamps = st.session_state.get("timestamps", [])

    import pandas as pd
    if timestamps and temps and hums:
        idx = pd.to_datetime([ts/1000.0 for ts in timestamps], unit='s')
        df = pd.DataFrame({"temperatura": temps, "humedad": hums}, index=idx)
        # evitando deprecación: usar width='stretch' en futuras versiones
        st.line_chart(df["temperatura"], height=250, width='stretch')
        st.line_chart(df["humedad"], height=250, width='stretch')
    else:
        st.write("No hay datos de temperatura/humedad todavía. Esperando telemetría desde el ESP32.")

    st.write("---")
    st.write("Control manual del servo desde esta página (al activarlo, moverá el servo a 90°).")
    if st.button("Activar servo (90°)"):
        publish_servo_cmd(client, 90)
        st.success("Comando servo enviado: 90°")

elif page == "Seguridad":
    st.header("Seguridad / PIR")
    status = st.session_state.get("security", "No se han detectado intrusos")
    if status == "Intruso detectado":
        st.error(status)
    else:
        st.success(status)

    st.write("Cuando el sensor PIR se active (evento 'motion'), esta página cambiará a 'Intruso detectado' automáticamente.")

    st.write("---")
    st.write("Comando de voz para seguridad: di 'seguridad' para mover el servo a 110°.")
    value = voice_recognition_component(key="voice_seguridad")
    if value and isinstance(value, dict) and value.get("text"):
        txt = value.get("text", "").lower()
        st.write("Reconocido:", txt)
        if "seguridad" in txt:
            publish_servo_cmd(client, 110)
            st.success("Comando enviado: mover servo a 110°")
        else:
            st.warning("No se reconoció la palabra 'seguridad' en el texto.")

# Footer / información de conexión MQTT
st.sidebar.write("MQTT broker:")
st.sidebar.write(f"{client.broker}:{client.port}")
st.sidebar.write("Último client id (si disponible):")
try:
    cid = client.client._client_id.decode() if hasattr(client.client, '_client_id') else ""
except Exception:
    cid = ""
st.sidebar.write(cid)
st.sidebar.write("Último payload /lights/state (raw):")
st.sidebar.write(st.session_state.get("last_lights_state_raw", "— no recibido —"))
