from picamera2.devices import IMX500
import configparser
from picamera2 import Picamera2
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection
import numpy as np
import cv2

config = configparser.ConfigParser()
config.read("config.ini")

# camera settings
model = config["CAMERA"]["model"]
height = int(config["CAMERA"]["height"])
width = int(config["CAMERA"]["width"])
iou = float(config["CAMERA"]["iou"])
threshold = float(config["CAMERA"]["threshold"])
max_detections = int(config["CAMERA"]["max_detections"])
inference_rate = int(config["CAMERA"]["inference_rate"])


def init_camera() -> tuple[Picamera2, IMX500]:
    """
    Initialize the camera and the IMX500 object
    :return: tuple of Picamera2 and IMX500 objects
    """
    # This must be called before instantiation of Picamera2
    imx500 = IMX500(model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Network is not an object detection task")
        exit()

    # Defaults
    if intrinsics.labels is None:
        with open("../assets/coco_labels.txt", "r") as f:
            intrinsics.labels = f.read().splitlines()
    intrinsics.update_with_defaults()

    intrinsics.inference_rate = inference_rate

    picam2 = Picamera2(imx500.camera_num)
    config = picam2.create_preview_configuration(
        controls={"FrameRate": intrinsics.inference_rate},
        buffer_count=12,
        main={"format": "XRGB8888", "size": (width, height)},
    )

    imx500.show_network_fw_progress_bar()
    picam2.start(config)

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    return picam2, imx500


def get_num_people_local(metadata: dict, imx500: IMX500) -> int:
    """
    Get the number of people detected in the frame
    :param metadata: metadata from the camera
    :param imx500: IMX500 object
    :return: number of people detected
    """
    np_outputs = imx500.get_outputs(metadata, add_batch=True)

    if np_outputs is None:
        return 0

    _, scores, classes = postprocess_nanodet_detection(
        outputs=np_outputs[0],
        conf=threshold,
        iou_thres=iou,
        max_out_dets=max_detections,
    )[0]
    ## parse how many people are in the frame
    num_persons = 0
    for score, category in zip(scores, classes):
        if score > threshold and category == 0:
            num_persons += 1

    return num_persons
