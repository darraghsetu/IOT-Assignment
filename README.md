
# IoT Standards & Protocols Assignment 25/26

# Learner Driver Mirror-Checking Checker

### Student Name: Darragh Drohan
### Student ID: 20105993

The idea for my project is a IoT Device that is used to capture video stream of a learner driver and analyse if they check their mirrors before an event such as stopping or turning.

## Tools, Technologies and Equipment

My idea of how this would be set up would a Raspberry Pi with an attached Pi Camera sensor. The video from the camera would be processed locally on the Pi using Python and a [Google MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/guide) library, specifically the [Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker). This should allow for identification of facial landmarks that would allow for analysis of the driver's head movement.

I would also use **simulated** sensor(s) to monitor the motion of a car using an accelerometer, gyroscope and possibly a GPS module. When an event occurs where the driver should have checked their mirrors is sensed, the head positioning in the last *x* seconds is checked for the correct orientation. In either of the cases a timestamped message is sent using MQTT with the event details. After a journey is finished a dashboard would be available where the driver could check the route taken (from GPS data dumped at the end of a journey) and details about when they failed to check their mirrors.

## Setup

Python 3.11 is required for this project, I would recommend using a Raspberry Pi with **Raspberry Pi OS (Legacy, 64-bit) Lite** for the OS, as this has Python 3.12.

You need to install some system libraries for mediapipe and picamera to work.
And then create a virtual environment and install the requirements.txt.
Assuming you are on a Pi with Python 3.11:

...To be continued

## Demo Video

https://github.com/user-attachments/assets/42c997d5-82fb-4c63-8f7d-eb8124876bdd
