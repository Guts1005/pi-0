#!/usr/bin/env python3
import os
import requests
import shutil
from utils import FAILED_IMAGES_DIR, FAILED_VIDEOS_DIR, FAILED_AUDIOS_DIR
from utils import get_rpi_serial

DEVICE_ID = get_rpi_serial()
# DEVICE_ID = "raspberry_pi_01"
UPLOAD_URL = "https://centrix.co.in/v_api/upload"
HEADERS = {"X-API-KEY": "DDjgMfxLqhxbNmaBoTkfBJkhMxNxkPwMgGjPUwCOaJRCBrvtUX"}

def handle_failed_upload(file_path, file_type):
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist, cannot move.")
        return
    if file_type == "image":
        target_dir = FAILED_IMAGES_DIR
    elif file_type == "audio":
        target_dir = FAILED_AUDIOS_DIR
    elif file_type == "video":
        target_dir = FAILED_VIDEOS_DIR
    else:
        return
    os.makedirs(target_dir, exist_ok=True)
    try:
        shutil.move(file_path, os.path.join(target_dir, os.path.basename(file_path)))
        print(f"Moved failed upload to {target_dir}")
    except Exception as e:
        print(f"Failed to move file {file_path}: {e}")

def upload_file(file_path, file_type, start_time="", end_time=""):
    try:
        with open(file_path, "rb") as f:
            files = {file_type: f}
            data = {
                "device_id": DEVICE_ID,
                "file_type": file_type,
                "start_time": start_time,
                "end_time": end_time
            }
            resp = requests.post(UPLOAD_URL, headers=HEADERS, files=files, data=data)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success"):
                return True, result
            else:
                handle_failed_upload(file_path, file_type)
                return False, result
        else:
            handle_failed_upload(file_path, file_type)
            return False, {"error": resp.text}
    except Exception as e:
        handle_failed_upload(file_path, file_type)
        return False, {"exception": str(e)}

def upload_image(file_path, start_time="", end_time=""):
    return upload_file(file_path, "video", start_time, end_time)

def upload_video(file_path, start_time="", end_time=""):
    return upload_file(file_path, "video", start_time, end_time)

def upload_audio(file_path, start_time="", end_time=""):
    return upload_file(file_path, "video", start_time, end_time)
