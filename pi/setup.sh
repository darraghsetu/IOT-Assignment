#!/bin/bash

export FERNET_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"

echo "Fernet Key set."
echo "Please set it on the server using the following command:"
echo "export FERNET_KEY='$FERNET_KEY'"

FACE_LANDMARKER_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"

if [ ! -f "face_landmarker.task" ]; then
    wget -q $FACE_LANDMARKER_URL
fi
