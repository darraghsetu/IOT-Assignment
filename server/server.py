import json
import paho.mqtt.client as mqtt
import threading
from ssl import CERT_REQUIRED
from flask import Flask, render_template
from pymongo import MongoClient
from os import environ
from sys import exit
from cryptography.fernet import Fernet

MQTT_BROKER_NAME = "broker.hivemq.com"
MQTT_PORT = 8883
MQTT_ID = "93951977-d4a3-4f1c-8b53-119467f9a9e3"
MQTT_TOPIC = MQTT_ID + '/mirror_checker'

mongo_client = MongoClient("127.0.0.1", 27017, directConnection=True)
db = mongo_client.mirror_checker_db
collection = db["journeys"]

app = Flask(__name__)
received_messages = set()

def get_cipher():
    key = environ["FERNET_KEY"]
    return Fernet(key.encode("utf-8"))

def decrypt_payload(encrypted_token):
    cipher = get_cipher()
    decrypted_json = cipher.decrypt(encrypted_token.encode("utf-8"))
    return json.loads(decrypted_json.decode("utf-8"))

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to Broker. Subscribing to: {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC, qos=1)
    else:
        print(f"Connection failed with code {rc}")

def on_message(client, userdata, msg):
    global received_messages

    try:
        encrypted_data = msg.payload.decode("utf-8")
        data = decrypt_payload(encrypted_data)
        msg_id = data.get('msg_id')

        if msg_id not in received_messages:
            received_messages.add(msg_id)

            journey_id = data.get('journey_id')
            event_name = data.get('event_name')
            timestamp = data.get('timestamp')
            result = data.get('result')
            checked = ", ".join(data.get('checked', []))
            missed = ", ".join(data.get('missed', []))

            print(f"\n--- New Event Received ---")
            print(f"Event: {event_name}")
            print(f"Time: {timestamp}")
            print(f"Result: {result}")
            print(f"Checked: {checked if checked else 'None'}")
            print(f"Missed: {missed if missed else 'None'}")

            db.journeys.update_one(
                {"journey_id": journey_id},
                {
                    "$setOnInsert": {"start_time": timestamp},
                    "$set": {"last_updated": timestamp},
                    "$push": {"events": data}
                },
                upsert = True
            )

    except Exception as e:
        print(f"Error processing message: {e}")

def run_mqtt():
    server_client = mqtt.Client(MQTT_ID + "_server_listener")
    server_client.tls_set(cert_reqs = CERT_REQUIRED)
    server_client.on_message = on_message
    server_client.on_connect = on_connect
    server_client.connect(MQTT_BROKER_NAME, MQTT_PORT)
    server_client.loop_forever()

@app.route('/')
def index():
    journeys = list(db.journeys.find().sort("last_updated", -1)) 
    return render_template('index.html', journeys=journeys)

@app.route('/journey/<journey_id>')
def journey_detail(journey_id):
    journey = db.journeys.find_one({"journey_id": journey_id}) 
    events = journey.get('events', [])
    total = len(events)
    passes = sum(1 for e in events if e.get('result') == 'PASS')
    score = (passes / total * 100) if total > 0 else 0

    return render_template('journey.html', journey_id=journey_id, events=events, score=round(score, 1))

def main():
    try:
        fernet_key = environ["FERNET_KEY"] 
    except KeyError as e:
        print("Error: You must setup the fernet key for client and server before running the program")
        print("Run 'source setup.sh' on the pi to generate and set the fernet key")
        exit(1)

    mqtt_thread = threading.Thread(target = run_mqtt, daemon = True)
    mqtt_thread.start()

    app.run(host='127.0.0.1', port=5000)

if __name__ == "__main__":
    main()
