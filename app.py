import json
import time
from queue import Queue, Empty

import streamlit as st
from bokeh.models import Button, CustomJS
from streamlit_bokeh_events import streamlit_bokeh_events
from streamlit.components.v1 import html

from mqtt_client import MQTTClient, TOPIC_LIGHTS_CMD, TOPIC_SERVO_CMD

# -----------------------
# Visual: background gradient (negro -> dorado)
# Insertar CSS antes de set_page_config para que aplique globalmente.
# -----------------------
st.markdown(
    """
    <style>
    /* Fondo degradado general: negro -> dorado */
    .stApp, .main, .block-container, .reportview-container {
      background: linear-gradient(180deg, #000000 0%, #D4AF37 100%) !important;
      background-attachment: fixed !important;
      color: #f5f3ee !important;
    }

    /* Sidebar: versión más oscura del degradado (para contraste) */
    [data-testid="stSidebar"] > div:first-child {
      background: linear-gradient(180deg, #000000 0%, #2b2b1f 100%) !important;
    }

    /* Hacer los contenedores ligeramente translúcidos para que se vea fondo */
    .css-1d391kg, .css-1lcbmhc, .stButton>button, .stTextInput>div, .stSelectbox>div {
      background: rgba(255,255,255,0.04) !important;
      color: #fff !important;
    }

    /* Encabezados y textos importantes en color dorado pálido */
    h1, h2, h3, h4, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
      color: #f6e7b1 !important;
    }
    .stMarkdown, .streamlit-expanderHeader, .stText, .stWrite {
      color: #f5f3ee !important;
    }

    /* Botones: borde dorado y fondo semitransparente */
    .stButton>button {
      border: 1px solid rgba(212,175,55,0.9) !important;
      background: rgba(255,255,255,0.03) !important;
      color: #fff !important;
    }
    .stButton>button:hover {
      background: rgba(212,175,55,0.08) !important;
      color: #fff !important;
    }

    /* Inputs / select / textareas: bordes dorados suaves */
    input, textarea, select {
      border: 1px solid rgba(212,175,55,0.14) !important;
      background: rgba(255,255,255,0.02) !important;
      color: #fff !important;
    }

    /* Tablas / códigos: fondo ligeramente más oscuro */
    .stDataFrame, pre, code {
      background: rgba(0,0,0,0.35) !important;
      color: #fff !important;
    }

    /* Gráficos Bokeh / Matplotlib: intentar forzar fondo transparente */
    .bk-root, .bk-plot, .bk-canvas {
      background: transparent !important;
    }

    /* Evitar scroll horizontal inesperado */
    html, body, .main {
      overflow-x: hidden !important;
    }

    /* Ajustes móviles / pequeños dispositivos: mantener legibilidad */
    @media (max-width: 640px) {
      .stApp, .block-container {
        padding-left: 8px !important;
        padding-right: 8px !important;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
        st.session_state.setdefault("temps", [])   # lista de valores de temperatura
        st.session_state.setdefault("hums", [])    # lista de valores de humedad
        st.session_state.setdefault("timestamps", [])  # lista de timestamps (ms)
        st.session_state.setdefault("security", "No se han detectado intrusos")
        # para depuración: último payload RAW recibido en /lights/state
        st.session_state.setdefault("last_lights_state_raw", None)
        # último timestamp (ms) de evento PIR 'motion'
        st.session_state.setdefault("last_motion_ts", None)
    return st.session_state["mqtt_client"]

# -----------------------
# Consumo robusto de la cola MQTT
# -----------------------
def mqtt_message_consumer():
    """
    Procesa todos los mensajes en la cola MQTT (st.session_state['mqtt_queue'])
    y actualiza st.session_state con temps, hums, light_state, security, etc.
    Es tolerante a tuplas (topic, parsed), (topic, parsed, raw) y otros formatos.
    """
    q = st.session_state.get("mqtt_queue")
    if not q:
        return
    updated = False
    try:
        while True:
            item = q.get_nowait()
            # Soportar tanto 2-tuplas (topic, parsed) como 3-tuplas (topic, parsed, raw)
            topic = None
            parsed = None
            raw = None
            try:
                if isinstance(item, tuple):
                    if len(item) == 3:
                        topic, parsed, raw = item
                    elif len(item) == 2:
                        topic, parsed = item
                        raw = None
                    elif len(item) >= 1:
                        topic = item[0]
                        parsed = item[1] if len(item) > 1 else None
                        raw = item[2] if len(item) > 2 else None
                elif isinstance(item, dict):
                    # fallback: attempt to extract keys
                    topic = item.get("topic")
                    parsed = item.get("parsed")
                    raw = item.get("raw")
                else:
                    # unknown format, try to index
                    try:
                        topic = item[0]
                        parsed = item[1] if len(item) > 1 else None
                        raw = item[2] if len(item) > 2 else None
                    except Exception:
                        continue
            except Exception:
                continue

            if not topic:
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

            # Lógica por topic
            if topic.endswith("/lights/state"):
                power = None
                if isinstance(parsed, dict):
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and "power" in data:
                        power = data.get("power")
                    if power is None and "power" in parsed:
                        power = parsed.get("power")
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
                if power is not None and isinstance(power, str):
                    p = power.lower()
                    if p in ("on", "off"):
                        st.session_state["light_state"] = p
                        updated = True

            elif topic.endswith("/temp/telemetry"):
                # Telemetría DHT22: t/h
                if isinstance(parsed, dict):
                    ts = parsed.get("ts", int(time.time()*1000))
                    data = parsed.get("data", {}) or {}
                    t = data.get("temp")
                    h = data.get("hum")
                    # tolerancia a formatos distintos
                    if t is None and isinstance(parsed.get("data"), dict):
                        t = parsed.get("data").get("temp")
                    if h is None and isinstance(parsed.get("data"), dict):
                        h = parsed.get("data").get("hum")
                    if t is not None or h is not None:
                        try:
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
                else:
                    if raw:
                        try:
                            tmp = json.loads(raw)
                            data = tmp.get("data", {}) or {}
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
                # parsing tolerante para 'motion'
                got_motion = False
                if isinstance(parsed, dict):
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and data.get("event") == "motion":
                        got_motion = True
                    if parsed.get("event") == "motion":
                        got_motion = True
                    if isinstance(data, str) and data == "motion":
                        got_motion = True
                if not got_motion and raw and "motion" in raw:
                    got_motion = True
                if got_motion:
                    st.session_state["security"] = "Intruso detectado"
                    # almacenar la hora del último evento motion en milisegundos
                    st.session_state["last_motion_ts"] = int(time.time() * 1000)
                    updated = True

            elif topic.endswith("/servo/state"):
                # opcional: manejar confirmaciones del servo si necesitas
                pass

    except Empty:
        pass

    if updated:
        # Forzar rerun seguro: solo usar experimental_rerun si existe
        try:
            rerun = getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
            else:
                # Evitar usar st.experimental_set_query_params (obsoleta) repetidamente
                # No forzamos rerun mediante query params para reducir log spam.
                pass
        except Exception:
            pass

# Publica comandos de luz / servo
def publish_light_cmd(client, on_or_off: str):
    payload = {"cmd": "power", "value": on_or_off}
    client.publish_json(TOPIC_LIGHTS_CMD, payload)

def publish_servo_cmd(client, angle: int):
    payload = {"angle": angle}
    client.publish_json(TOPIC_SERVO_CMD, payload)

# -----------------------
# Voice (Bokeh) helper - RESTAURADO
# -----------------------
def voice_bokeh_button(event_name: str, comp_id: str, label: str = "Iniciar reconocimiento"):
    js = f"""
    if (!window.speechRecognitionInstances) {{
        window.speechRecognitionInstances = {{}};
    }}
    const comp = "{comp_id}";
    const eventName = "{event_name}";
    const existing = window.speechRecognitionInstances[comp];

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {{
        document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify({{error: "no_speech_api", component: comp}})}}));
    }} else {{
        if (existing && existing._running) {{
            try {{ existing.stop(); }} catch(e){{}}
            existing._running = false;
            document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify({{event: "stopped", component: comp}})}}));
        }} else {{
            let recognition = existing;
            if (!recognition) {{
                recognition = new SpeechRec();
                recognition.lang = "es-ES";
                recognition.interimResults = false;
                recognition.continuous = false;
                recognition.onresult = function(e) {{
                    var value = "";
                    for (var i = e.resultIndex; i < e.results.length; ++i) {{
                        if (e.results[i].isFinal) {{
                            value += e.results[i][0].transcript;
                        }}
                    }}
                    if (value != "") {{
                        const payload = {{text: value.trim(), component: comp}};
                        document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify(payload)}}));
                    }}
                }};
                recognition.onerror = function(ev) {{
                    const payload = {{error: ev.error, component: comp}};
                    document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify(payload)}}));
                }};
                recognition.onend = function() {{
                    recognition._running = false;
                    document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify({{event: "ended", component: comp}})}}));
                }};
                window.speechRecognitionInstances[comp] = recognition;
            }}
            try {{
                recognition._running = true;
                recognition.start();
            }} catch(e) {{
                document.dispatchEvent(new CustomEvent(eventName, {{detail: JSON.stringify({{error: String(e), component: comp}})}}));
            }}
        }}
    }}
    """
    btn = Button(label=label, width=220)
    btn.js_on_event("button_click", CustomJS(code=js))
    return btn

# -----------------------
# Interfaz Streamlit
# -----------------------
st.set_page_config(page_title="ESP32 — Control y Monitor", layout="wide")
st.title("ESP32 — Interfaz Streamlit (MQTT + Voz)")

# Inicializa y procesa cola MQTT inmediatamente
client = get_mqtt_client()
mqtt_message_consumer()

# Sincronizar light_state desde last_lights_state_raw (si existe)
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

# Sidebar páginas
page = st.sidebar.selectbox("Páginas", ["Luz", "Sensores", "Seguridad"])

# --- PÁGINA LUZ ---
if page == "Luz":
    st.header("Control de luz (voz)")
    st.write("Usa el botón o el reconocimiento por voz. Di 'Encender' o 'Apagar'.")

    col1, col2 = st.columns([1, 3])

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
    st.write("Reconocimiento por voz (Bokeh). Pulsa 'Iniciar reconocimiento' y habla en español (Chrome/Edge recom.)")

    # Componente Bokeh para voz (restaurado)
    btn_luz = voice_bokeh_button(event_name="GET_TEXT_LUZ", comp_id="luz", label="Iniciar reconocimiento (voz)")
    result = streamlit_bokeh_events(
        btn_luz,
        events="GET_TEXT_LUZ",
        key="voice_listen_luz",
        debounce_time=0,
        override_height=80,
    )

    if result and "GET_TEXT_LUZ" in result:
        raw = result.get("GET_TEXT_LUZ")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"text": raw}
        if payload.get("text"):
            txt = payload.get("text", "").lower()
            st.write("Reconocido:", txt)
            if "encender" in txt:
                publish_light_cmd(client, "on")
                st.session_state["light_state"] = "on"
                st.session_state["last_lights_state_raw"] = json.dumps({
                    "ts": int(time.time() * 1000),
                    "device": "esp32-01",
                    "data": {"power": "on"}
                }, ensure_ascii=False)
                st.success("Comando enviado: encender")
            elif "apagar" in txt:
                publish_light_cmd(client, "off")
                st.session_state["light_state"] = "off"
                st.session_state["last_lights_state_raw"] = json.dumps({
                    "ts": int(time.time() * 1000),
                    "device": "esp32-01",
                    "data": {"power": "off"}
                }, ensure_ascii=False)
                st.success("Comando enviado: apagar")
            else:
                st.warning("No se reconoció 'encender' ni 'apagar' en el texto.")
        elif payload.get("error"):
            st.error(f"Error de reconocimiento: {payload.get('error')}")
        elif payload.get("event") == "stopped":
            st.info("Reconocimiento detenido.")
        elif payload.get("event") == "ended":
            st.info("Reconocimiento finalizado.")

    # Mostrar estado
    st.write("Estado actual de la luz:")
    light_state = st.session_state.get("light_state", "unknown")
    if light_state == "on":
        st.success("La luz está ENCENDIDA")
    elif light_state == "off":
        st.info("La luz está APAGADA")
    else:
        st.write("Estado desconocido (esperando mensaje retained del dispositivo).")

    st.write("Último payload recibido en /lights/state (raw):")
    st.code(st.session_state.get("last_lights_state_raw", "— no recibido —"))
