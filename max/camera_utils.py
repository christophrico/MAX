import configparser
import logging
import time
import numpy as np

from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection

# Load configuration
config = configparser.ConfigParser()
config.read("config.ini")

# Camera settings
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
    logging.info("Initializing camera and IMX500")

    # This must be called before instantiation of Picamera2
    imx500 = IMX500(model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
        logging.info("Created new NetworkIntrinsics with object detection task")
    elif intrinsics.task != "object detection":
        logging.error("Network is not an object detection task")
        exit(1)

    # Defaults
    if intrinsics.labels is None:
        try:
            with open("../assets/coco_labels.txt", "r") as f:
                intrinsics.labels = f.read().splitlines()
                logging.info(
                    f"Loaded {len(intrinsics.labels)} labels from coco_labels.txt"
                )
        except Exception as e:
            logging.error(f"Failed to load labels: {e}")
            exit(1)

    intrinsics.update_with_defaults()
    intrinsics.inference_rate = inference_rate

    logging.info(f"Camera configuration: {width}x{height} at {inference_rate} FPS")
    logging.info(
        f"Detection settings: IoU={iou}, threshold={threshold}, max_detections={max_detections}"
    )

    picam2 = Picamera2(imx500.camera_num)
    camera_config = picam2.create_preview_configuration(
        controls={"FrameRate": intrinsics.inference_rate},
        buffer_count=12,
        main={"format": "XRGB8888", "size": (width, height)},
    )

    logging.info("Loading network firmware...")
    imx500.show_network_fw_progress_bar()

    picam2.start(camera_config)
    logging.info("Camera started successfully")

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()
        logging.info("Auto aspect ratio enabled")

    return picam2, imx500


def get_num_people_local(metadata: dict, imx500: IMX500) -> int:
    """
    Get the number of people detected in the frame
    :param metadata: metadata from the camera
    :param imx500: IMX500 object
    :return: number of people detected
    """
    try:
        np_outputs = imx500.get_outputs(metadata, add_batch=True)

        if np_outputs is None:
            return 0

        _, scores, classes = postprocess_nanodet_detection(
            outputs=np_outputs[0],
            conf=threshold,
            iou_thres=iou,
            max_out_dets=max_detections,
        )[0]

        # Parse how many people are in the frame
        num_persons = 0
        for score, category in zip(scores, classes):
            if score > threshold and category == 0:  # Person class is typically 0
                num_persons += 1

        return num_persons

    except Exception as e:
        logging.error(f"Error detecting people: {e}")
        return 0


def capture_frame(camera) -> np.ndarray:
    """
    Capture a frame from the camera

    Args:
        camera: Picamera2 object

    Returns:
        numpy.ndarray: Captured frame or None if failed
    """
    try:
        frame = camera.capture_array()
        if frame is None:
            logging.error("Camera returned None frame")
        else:
            logging.debug(f"Captured frame with shape: {frame.shape}")
        return frame
    except Exception as e:
        logging.error(f"Error capturing frame: {e}")
        return None


def capture_frame_with_metadata(camera, imx500):
    """
    Capture a frame and extract metadata including person detection

    Args:
        camera: Picamera2 object
        imx500: IMX500 object

    Returns:
        tuple: (frame, people_count) or (None, 0) if failed
    """
    try:
        # Capture frame
        frame = capture_frame(camera)
        if frame is None:
            return None, 0

        # Get metadata and detect people
        metadata = camera.capture_metadata()
        people_count = get_num_people_local(metadata, imx500)
        logging.debug(f"Detected {people_count} people in frame")

        return frame, people_count
    except Exception as e:
        logging.error(f"Error capturing frame with metadata: {e}")
        return None, 0


def get_frame_for_display(camera, state):
    """
    Get the appropriate frame for display based on application state

    Args:
        camera: Picamera2 object
        state: Application state

    Returns:
        numpy.ndarray: Frame to display
    """
    try:
        display_local = state["display_local"]
        remote_frame = state.get("remote_frame")

        if display_local or remote_frame is None:
            # Display local frame
            frame = capture_frame(camera)
            logging.debug("Using local frame for display")
        else:
            # Display remote frame
            frame = remote_frame
            logging.debug("Using remote frame for display")

        return frame
    except Exception as e:
        logging.error(f"Error getting frame for display: {e}")
        # Fallback to local frame on error
        return capture_frame(camera)
