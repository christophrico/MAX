import argparse
import sys
from functools import lru_cache
import socket
import threading
import configparser
import struct
import msgpack

import cv2
import numpy as np

from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection

config = configparser.ConfigParser()
config.read("config.ini")

# Global variables
REMOTE_IP = config['REMOTE']['ip']
REMOTE_PORT = int(config['REMOTE']['port'])

last_detections = []


def parse_detections(metadata: dict):
    global last_detections
    labels = get_labels()
    threshold = args.threshold
    iou = args.iou
    max_detections = args.max_detections

    np_outputs = imx500.get_outputs(metadata, add_batch=True)

    if np_outputs is None:
        return last_detections
    
    _, scores, classes = \
        postprocess_nanodet_detection(outputs=np_outputs[0], conf=threshold, iou_thres=iou,
                                        max_out_dets=max_detections)[0]

    labels_to_return = []
    for score, category in zip(scores, classes):
        if score > threshold:
            labels_to_return.append(labels[int(category)])

    return labels_to_return


@lru_cache
def get_labels():
    labels = intrinsics.labels

    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels



def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, help="Path of the model",
                        default="/usr/share/imx500-models/imx500_network_nanodet_plus_416x416.rpk")
    parser.add_argument("--fps", type=int, help="Frames per second")
    parser.add_argument("--threshold", type=float, default=0.40, help="Detection threshold")
    parser.add_argument("--max-detections", type=int, default=10, help="Set max detections")
    parser.add_argument("--iou", type=float, default=0.50, help="Set iou threshold")
    parser.add_argument("--labels", type=str,
                        help="Path to the labels file")
    parser.add_argument("--print-intrinsics", action="store_true",
                        help="Print JSON network_intrinsics then exit")
    return parser.parse_args()




if __name__ == "__main__":
    args = get_args()

    # This must be called before instantiation of Picamera2
    imx500 = IMX500(args.model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Network is not an object detection task", file=sys.stderr)
        exit()

    # Override intrinsics from args
    for key, value in vars(args).items():
        if key == 'labels' and value is not None:
            with open(value, 'r') as f:
                intrinsics.labels = f.read().splitlines()
        elif hasattr(intrinsics, key) and value is not None:
            setattr(intrinsics, key, value)

    # Defaults
    if intrinsics.labels is None:
        with open("assets/coco_labels.txt", "r") as f:
            intrinsics.labels = f.read().splitlines()
    intrinsics.update_with_defaults()

    intrinsics.inference_rate  = 24

    if args.print_intrinsics:
        print(intrinsics)
        exit()

    height =480
    width=640

    picam2 = Picamera2(imx500.camera_num)
    config = picam2.create_preview_configuration(controls={"FrameRate": intrinsics.inference_rate}, buffer_count=12,
                                                 main={"format": 'XRGB8888', "size": (width, height)})

    imx500.show_network_fw_progress_bar()
    picam2.start(config)


    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote_socket.connect((REMOTE_IP, REMOTE_PORT))

    last_results = None

    while True:

        # get the image
        frame = picam2.capture_array()
        #cv2.imshow('f', frame)
        #cv2.waitKey(1)

        #get the metadata and parse the number of people in frame
        metadata = picam2.capture_metadata()
        last_results = parse_detections(metadata)
        number_of_persons = last_results.count('person')

        # Encode the frame as JPEG
        _, frame_encoded = cv2.imencode('.jpg', frame)
        frame_data = frame_encoded.tobytes()
        
        # Use msgpack to create a lightweight serialized payload
        payload = msgpack.packb({'frame': frame_data, 'number_of_persons': number_of_persons}, use_bin_type=True)
        
        # Send the size of the data and then the payload
        data_size = struct.pack("I", len(payload))
        remote_socket.sendall(data_size + payload)
                                               
    