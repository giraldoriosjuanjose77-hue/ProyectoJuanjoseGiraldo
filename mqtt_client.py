import json
import threading
import time
from queue import Queue

import paho.mqtt.client as mqtt

# MQTT defaults (coincide con tu .ino)
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
BASE_TOPIC = "giraldoriosjuanjose77-hue"

TOPIC_LIGHTS_CMD = f"{BASE_TOPIC}/lights/cmd"
TOPIC_LIGHTS_STATE = f"{BASE_TOPIC}/lights/state"
TOPIC_TEMP_TELE = f"{BASE_TOPIC}/temp/telemetry"
TOPIC_SERVO_CMD = f"{BASE_TOPIC}/servo/cmd"
TOPIC_SERVO_STATE = f"{BASE_TOPIC}/servo/state"
TOPIC_SECURITY_EVENT = f"{BASE_TOPIC}/security/event"
TOPIC_SECURITY_CMD = f"{BASE_TOPIC}/security/cmd"

class MQTTClient:
    """
    Simple wrapper around paho-mqtt that publishes/subscribes and pushes parsed messages
    into a Queue for consumption by the Streamlit app.
    """
    def __init__(self, broker=MQTT_BROKER, port=MQTT_PORT, queue: Queue = None):
        self.client = mqtt.Client()
        self.broker = broker
        self.port = port
        self.queue = queue or Queue()
        self._thread = None
        self._stop_event = threading.Event()

        # bind callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
        except Exception as e:
            # The app will retry in a simple loop
            print("MQTT connect error:", e)
        self.client.loop_start()
        # keep thread alive until stop requested
        while not self._stop_event.is_set():
            time.sleep(0.1)
        self.client.loop_stop()

    def stop(self):
        self._stop_event.set()
        try:
            self.client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc):
        print("MQTT connected, rc=", rc)
        # subscribe to relevant topics
        client.subscribe(TOPIC_LIGHTS_STATE)
        client.subscribe(TOPIC_TEMP_TELE)
        client.subscribe(TOPIC_SERVO_STATE)
        client.subscribe(TOPIC_SECURITY_EVENT)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8', errors='ignore')
        # try parse JSON
        try:
            obj = json.loads(payload)
        except Exception:
            obj = payload
        # push to queue
        self.queue.put((topic, obj))

    def publish_json(self, topic, payload_dict, retain=False):
        payload = json.dumps(payload_dict)
        self.client.publish(topic, payload, retain=retain)

    def publish_raw(self, topic, payload_str, retain=False):
        self.client.publish(topic, payload_str, retain=retain)
