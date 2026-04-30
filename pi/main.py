import os

# Quietening libcamera and mediapipe logging, its hacky but necessary for clean terminal
# Generative AI disclosure: The following line of code is AI generated
# The conversation can be viewed here: https://gemini.google.com/share/f413a4af61d5
os.dup2(os.open(os.devnull, os.O_RDWR), 2)

import time
import json
import threading
import numpy as np
import mediapipe as mp
import paho.mqtt.client as mqtt
from sys import exit
from pathlib import Path
from collections import deque
from uuid import uuid4
from ssl import CERT_REQUIRED
from cryptography.fernet import Fernet
from datetime import datetime
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from picamera2 import Picamera2

# Configurable constants

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 640
CAMERA_FPS = 30

MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task'
LOOKBACK_WINDOW_SECONDS = 5
CENTRE_TOLERANCE_DEGREES = 10
PROCESS_EVERY_N_FRAMES = 3

MQTT_ID = "93951977-d4a3-4f1c-8b53-119467f9a9e3"
MQTT_CLIENT_NAME = MQTT_ID + '_mirror_checker'
MQTT_TOPIC = MQTT_ID + '/mirror_checker'
MQTT_QOS = 1
MQTT_BROKER_NAME = "broker.hivemq.com" # mosquitto stopped working for me for some reason
MQTT_PORT = 8883

CALIBRATION_FILENAME = "calibration.json"
MODEL_FILENAME = "face_landmarker.task"

# Mirror constants

AHEAD = "AHEAD"
REAR_MIRROR = "REAR_VIEW_MIRROR"
LEFT_MIRROR = "LEFT_MIRROR"
RIGHT_MIRROR = "RIGHT_MIRROR"

HEAD_POSITIONS = [AHEAD, REAR_MIRROR, LEFT_MIRROR, RIGHT_MIRROR]

CALIBRATION_PROMPTS = {
    AHEAD: "Look straight ahead",
    REAR_MIRROR: "Look up at your rear view mirror",
    LEFT_MIRROR: "Look at your left door mirror",
    RIGHT_MIRROR: "Look at your right door mirror"
}

# Event constants

MOVE_OFF = "MOVE_OFF"
SLOW_DOWN = "SLOW_DOWN"
REVERSE = "REVERSE"
TURN_LEFT = "TURN_LEFT"
TURN_RIGHT = "TURN_RIGHT"
LANE_CHANGE_LEFT = "LANE_CHANGE_LEFT"
LANE_CHANGE_RIGHT = "LANE_CHANGE_RIGHT"

EVENTS = [MOVE_OFF, SLOW_DOWN, REVERSE, TURN_LEFT, TURN_RIGHT, LANE_CHANGE_LEFT, LANE_CHANGE_RIGHT]

EVENT_MIRRORS = {
    MOVE_OFF: [REAR_MIRROR, RIGHT_MIRROR],
    SLOW_DOWN: [REAR_MIRROR],
    REVERSE: [REAR_MIRROR],
    TURN_LEFT: [REAR_MIRROR, LEFT_MIRROR],
    TURN_RIGHT: [REAR_MIRROR, RIGHT_MIRROR],
    LANE_CHANGE_LEFT: [REAR_MIRROR, LEFT_MIRROR],
    LANE_CHANGE_RIGHT: [REAR_MIRROR, RIGHT_MIRROR]
}

KEY_BINDINGS = {
    "mo": MOVE_OFF,
    "sd": SLOW_DOWN,
    "r": REVERSE,
    "tl": TURN_LEFT,
    "tr": TURN_RIGHT,
    "lcl": LANE_CHANGE_LEFT,
    "lcr": LANE_CHANGE_RIGHT
}

# Global variables

camera = None
mediapipe = None
centres = {}
recent_checks = deque()
last_checked = None
calibrated = False
journey_active = False
journey_id = None
latest_input = None
unsent_message_ids = []
mqtt_client = None
fernet_key = None

def _get_cipher():
    return Fernet(fernet_key.encode("utf-8"))

def encrypt_payload(payload):
    cipher = _get_cipher()
    token = cipher.encrypt(payload.encode("utf-8"))
    return token.decode("utf-8")

def on_publish(client, userdata, mid):
    global unsent_message_ids

    if mid in unsent_message_ids:
        unsent_message_ids.remove(mid)

def connect_mqtt():
    global mqtt_client 

    mqtt_client = mqtt.Client(MQTT_CLIENT_NAME)
    mqtt_client.on_publish = on_publish
    mqtt_client.tls_set(cert_reqs=CERT_REQUIRED)
    mqtt_client.connect(MQTT_BROKER_NAME, MQTT_PORT)
    mqtt_client.loop_start()

def input_listener():
    global journey_active, latest_input

    while True:
        user_input = input("").strip().lower()
        
        if user_input == "":
            print("\033[A", end="\r")

        if user_input is not None:
            if journey_active:
                match user_input:
                    case 'q':
                        journey_active = False
                    case key if key in KEY_BINDINGS:
                        evaluate(KEY_BINDINGS[key])
                    case _:
                        print("Command not recognised")
            else:
                latest_input = user_input

def evaluate(event_name):
    result = "FAIL"
    timestamp = datetime.now().isoformat()
    now = time.monotonic()
    cutoff = now - LOOKBACK_WINDOW_SECONDS
    remove_outdated_events(cutoff)
    
    required_checks = EVENT_MIRRORS[event_name]
    checked = []
    missed = []

    recent_names = []
    for check in recent_checks:
        recent_names.append(check['name'])

    for mirror_name in required_checks:
        if mirror_name in recent_names:
            checked.append(mirror_name)
        else:
            missed.append(mirror_name)

    num_required = len(required_checks)
    num_checked = len(checked)
    num_missed = len(missed)

    if not missed:
        result = "PASS"

    print()
    print(f"--- {event_name} Check ---")
    print(f"{num_checked}/{num_required} mirrors checked")
    print(f"RESULT: {result}")

    if missed:
        print(f"Missing check(s): {', '.join(missed)}")

    print()

    msg_id = str(uuid4())

    report = {
        'msg_id': msg_id,
        'journey_id': journey_id,
        'event_name': event_name,
        'timestamp': timestamp,
        'result': result,
        'checked': checked,
        'missed': missed
    }

    payload = encrypt_payload(json.dumps(report))
    message = mqtt_client.publish(MQTT_TOPIC, payload, qos = MQTT_QOS, retain = False)
    unsent_message_ids.append(message.mid)

def remove_outdated_events(cutoff):
    global recent_checks

    while len(recent_checks) > 0:
        if recent_checks[0]['timestamp'] < cutoff:
            recent_checks.popleft()
        else:
            break

def clean_and_exit(status):
    global camera, mqtt_client

    if camera is not None:
        camera.stop()
    
    timeout = 20
    start_time = time.monotonic()

    if unsent_message_ids:
        print(f"Waiting for {len(unsent_message_ids)} message(s) to be sent to server, please wait.")
        while unsent_message_ids and (time.monotonic() - start_time < timeout):
            time.sleep(0.1)

    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

    exit(status) #sys.exit

def validate_check(yaw, pitch):
    closest_name = None
    closest_distance = float('inf')

    for name, centre in centres.items():
        dist = distance_from(yaw, pitch, centre['yaw'], centre['pitch'])

        if dist < closest_distance:
            closest_distance = dist
            closest_name = name

    if closest_distance < CENTRE_TOLERANCE_DEGREES and closest_name != last_checked:
        return closest_name
    return None

def distance_from(yaw1, pitch1, yaw2, pitch2):
    yaw_dist = (yaw1 - yaw2)
    pitch_dist = (pitch1 - pitch2)
    
    return np.hypot(yaw_dist, pitch_dist) # sqrt( (yaw * yaw) + (pitch * pitch) )

def print_key_bindings():
    print()
    print("╔" + ("═" * 28) + "╗")
    print("║" + (" " * 10) + "Controls" + (" " * 10) + "║")
    print("╠" + ("═" * 5) + "╦" + ("═" * 22) + "╣")

    for key, value in KEY_BINDINGS.items():
        print("║" + f" {key} " + (" " * (3 - len(key))) + "║" + f" {value} " + (" " * (20 - len(value))) + "║")
        print("╠" + ("═" * 5) + "╬" + ("═" * 22) + "╣") 

    print("║" + " q " + (" " * 2) + "║" + " end journey " + (" " * 9) + "║")
    print("╚" + ("═" * 5) + "╩" + ("═" * 22) + "╝") 
    print()

def print_journey_instructions():
    print_key_bindings()
    print("Camera is now registering head movements.")
    print("To register a car-based event has begun, enter in the corresponding control and press ENTER")
    print()

def run():
    global journey_active, last_checked, journey_id

    print_journey_instructions()

    frame_count = 0
    journey_id = str(uuid4())

    while journey_active:
        frame = camera.capture_array()
        frame_count += 1

        if frame_count % PROCESS_EVERY_N_FRAMES == 0:
            mp_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = frame)
            result = mediapipe.detect(mp_image)
            head_pose = get_head_pose(result)

            if head_pose is not None:
                yaw, pitch, roll = head_pose
                mirror_checked = validate_check(yaw, pitch)

                if mirror_checked is not None:
                    last_checked = mirror_checked
                    timestamp = time.strftime("%H:%M:%S")
                    now = time.monotonic()
                    print(f"[{timestamp}] Checked {mirror_checked}")
                    recent_checks.append({'name': mirror_checked, 'timestamp': now})

def setup():
    global camera, centres, calibrated, mediapipe, fernet_key

    # Check for fernet key
    try:
        fernet_key = os.environ["FERNET_KEY"] 
    except KeyError as e:
        print("You must setup the fernet key for client and server before running the program")
        print("Run 'source setup.sh' to generate and set the fernet key")
        clean_and_exit(1)

    # Check for face_landmarker.task
    model_file = Path(MODEL_FILENAME)

    if not model_file.exists():
        print("You must download the face landmarker mediapipe model before running the program")
        print("Run 'source setup.sh' to download the model")
        print(f"Or download directly from: {MODEL_URL}")
        clean_and_exit(1)

    # Start Picamera
    camera = Picamera2()
    config = camera.create_preview_configuration(
        main = {"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
    )
    camera.configure(config)
    camera.start()
    time.sleep(1)

    # Check for calibration file
    calibration_file = Path(CALIBRATION_FILENAME)

    if calibration_file.exists():
        with open(CALIBRATION_FILENAME, "r") as file:
            centres = json.load(file)
            calibrated = True

    # Load MediaPipe Model
    options = mp_vision.FaceLandmarkerOptions(
        base_options = mp_python.BaseOptions(model_asset_path = MODEL_FILENAME),
        running_mode = mp_vision.RunningMode.IMAGE,
        num_faces = 1,
        output_face_blendshapes = False,
        output_facial_transformation_matrixes = True,
        min_face_detection_confidence = 0.5,
        min_face_presence_confidence = 0.5,
        min_tracking_confidence = 0.5
    )

    mediapipe = mp_vision.FaceLandmarker.create_from_options(options)

    # Connect to MQTT broker
    connect_mqtt()

    # Start listening for user input
    thread = threading.Thread(target = input_listener, daemon = True)
    thread.start()

# AI Disclosure: The following function was generated by AI
# The conversation can be viewed at: https://gemini.google.com/share/33f81795dde1
def get_head_pose(result):
    """
    Extracts yaw, pitch, and roll in degrees from a MediaPipe FaceLandmarkerResult
    for a single detected face.
    """
    if not result.facial_transformation_matrixes:
        return None

    # Get the 4x4 transformation matrix and convert to 3x3 rotation
    matrix = np.array(result.facial_transformation_matrixes[0])
    R = matrix[:3, :3]
    
    # Calculate the scale factor to check for gimbal lock (vertical gimbal)
    sy = np.sqrt(R[0, 0]**2 + R[1, 0]**2)
    singular = sy < 1e-6

    if not singular:
        # Standard calculation
        pitch = np.arctan2(R[2, 1], R[2, 2])
        yaw   = np.arctan2(-R[2, 0], sy)
        roll  = np.arctan2(R[1, 0], R[0, 0])
    else:
        # Gimbal lock fallback (occurs when looking straight up or down)
        pitch = np.arctan2(-R[1, 2], R[1, 1])
        yaw   = np.arctan2(-R[2, 0], sy)
        roll  = 0

    # Convert radians to degrees
    return (float(np.degrees(yaw)), float(np.degrees(pitch)), float(np.degrees(roll)))

def run_calibration():
    global centres, latest_input, calibrated
    print("\n--- Starting Calibration ---\n")
    print("-" * 20)
    
    for position in HEAD_POSITIONS:
        print(f"{CALIBRATION_PROMPTS[position]} and press ENTER, then wait three seconds")

        latest_input = None

        while True:
            if latest_input == "":
                latest_input = None
                break
            time.sleep(0.1)

        successful_frames_captured = 0
        yaw_sum = 0.0
        pitch_sum = 0.0

        while successful_frames_captured < 30: 
            frame = camera.capture_array()
            mp_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = frame)
            result = mediapipe.detect(mp_image)

            if result.facial_transformation_matrixes:
                successful_frames_captured += 1
                yaw, pitch, roll = get_head_pose(result)
                yaw_sum += yaw
                pitch_sum += pitch

        yaw_avg = yaw_sum / 30
        pitch_avg = pitch_sum / 30

        centres[position] = {"yaw": yaw_avg, "pitch": pitch_avg}
        print(f"Success: {position} calibrated at: yaw = {yaw_avg:.2f} Degrees, pitch = {pitch_avg:.2f} Degrees")
        print('-' * 20)

    with open(CALIBRATION_FILENAME, "w") as file:
        json.dump(centres, file, indent=2)
    print(f"\nCalibrations saved to {CALIBRATION_FILENAME}")

    calibrated = True

def print_menu():
    print()
    print("╔" + ("═" * 38) + "╗")
    print("║" + (" " * 4) + "Learner Driver Mirror Checker" + (" " * 5) + "║")
    print("╠" + ("═" * 38) + "╣")
    print("║" + " 1. Calibrate Mirrors" + (" " * 17) + "║")
    print("╠" + ("═" * 38) + "╣")
    print("║" + " 2. Start New Journey" + (" " * 17) + "║")
    print("╠" + ("═" * 38) + "╣")
    print("║" + " 0. Exit" + (" " * 30) + "║")
    print("╚" + ("═" * 38) + "╝") 
    print(" > ", end = "", flush = True)

def menu():
    global latest_input, journey_active

    setup()
    
    while True:
        print_menu()

        while latest_input is None:
            time.sleep(0.1)

        user_input = latest_input
        latest_input = None
        
        match user_input:
            case "1":
                run_calibration()
            case "2":
                if calibrated:
                    journey_active = True
                    run()
                else:
                    print("You must calibrate the position of your mirrors before starting a journey.")
            case "0":
                clean_and_exit(0)
            case _:
                print("Invalid menu option. Please try again.")

if __name__ == "__main__":
    menu()
