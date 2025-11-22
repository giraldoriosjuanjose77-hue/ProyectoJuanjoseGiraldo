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
            # ahora esperamos tupla (topic, parsed_obj_or_None, raw_payload)
            topic, parsed, raw = q.get_nowait()
            # Para depuración, si el topic es lights/state almacenamos el raw
            if topic.endswith("/lights/state"):
                st.session_state["last_lights_state_raw"] = raw

            # topic checks
            if topic.endswith("/lights/state"):
                # estado luz
                # Solo actualizamos si encontramos un campo "power" con "on" o "off"
                power = None
                if isinstance(parsed, dict):
                    # mirar en data.power
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and "power" in data:
                        power = data.get("power")
                    # también aceptar payloads con clave directa "power"
                    if not power and "power" in parsed:
                        power = parsed.get("power")
                    # si el payload tiene { "state": "online" } no tocar el estado de la luz
                # Si parsed es None (no JSON), intentamos heurística en raw
                if power is None and isinstance(raw, str):
                    # intentar buscar '"power":' en el raw con un parseo simple
                    if '"power"' in raw:
                        try:
                            tmp = json.loads(raw)
                            if isinstance(tmp, dict):
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
                        else:
                            # valor inesperado -> guardar raw para depuración
                            st.session_state["last_lights_state_raw"] = raw
                    else:
                        # power no es string, ignorar y guardar raw
                        st.session_state["last_lights_state_raw"] = raw

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
                        # keep reasonable history
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
                # manejar confirmaciones del servo si quieres (no obligatorio)
                pass
    except Empty:
        pass
    if updated:
        # Fuerza actualización de la interfaz para reflejar cambios entrantes.
        try:
            st.experimental_rerun()
        except Exception:
            pass

# Publica comandos de luz (matching tu .ino)
def publish_light_cmd(client, on_or_off: str):
    # json: {"cmd":"power","value":"on"/"off"}
    payload = {"cmd": "power", "value": on_or_off}
    client.publish_json(TOPIC_LIGHTS_CMD, payload)

def publish_servo_cmd(client, angle: int):
    # tu .ino escucha { "angle": <n> } en servo/cmd
    payload = {"angle": angle}
    client.publish_json(TOPIC_SERVO_CMD, payload)

# Componente HTML para reconocimiento de voz
def voice_recognition_component(key="voice"):
    # Carga el HTML y devuelve lo que posteó (obj) o None
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
        # palabras esperadas en español
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

# (El resto de páginas se mantiene igual; no se muestran aquí para brevedad)
# ... (Sensores y Seguridad como antes)
