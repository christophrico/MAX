import configparser
import logging
import zmq
import time
import msgpack

import cv2
import numpy as np

from state_class import ThreadSafeState
from camera_utils import get_num_people_local


def init_connection() -> zmq.Context:
    """Initialize ZeroMQ context"""
    return zmq.Context()


def init_publisher(zmq_context, config) -> zmq.Socket:
    """Initialize ZeroMQ publisher socket for sending frames"""
    local_port = int(config["LOCAL"]["port"])
    publisher = zmq_context.socket(zmq.PUB)
    publisher.bind(f"tcp://*:{local_port}")
    logging.info(f"Publisher bound to port {local_port}")
    return publisher


def init_subscriber(zmq_context, config) -> zmq.Socket:
    """Initialize ZeroMQ subscriber socket for receiving frames"""
    remote_ip = config["REMOTE"]["ip"]
    remote_port = int(config["REMOTE"]["port"])
    subscriber = zmq_context.socket(zmq.SUB)
    subscriber.connect(f"tcp://{remote_ip}:{remote_port}")
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all messages
    subscriber.setsockopt(zmq.RCVTIMEO, 1000)  # 1000ms timeout
    logging.info(f"Subscriber connected to {remote_ip}:{remote_port}")
    return subscriber


# ---------------------- Send Frame Functions ----------------------


def encode_frame(frame, quality=70):
    """
    Encode a frame for network transmission

    Args:
        frame: OpenCV frame to encode
        quality: JPEG quality (0-100)

    Returns:
        bytes: Encoded frame data or None if encoding failed
    """
    try:
        _, encoded_frame = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        frame_data = encoded_frame.tobytes()
        logging.debug(f"Encoded frame to {len(frame_data)} bytes")
        return frame_data
    except Exception as e:
        logging.error(f"Error encoding frame: {e}")
        return None


def create_frame_metadata(people_count):
    """
    Create metadata for a frame

    Args:
        people_count: Number of people detected in the frame

    Returns:
        bytes: Packed metadata
    """
    metadata_dict = {"people_count": people_count, "timestamp": time.time()}
    packed_metadata = msgpack.packb(metadata_dict)
    logging.debug(f"Created metadata with {people_count} people")
    return packed_metadata


def publish_frame(publisher, metadata, frame_data):
    """
    Publish a frame and its metadata

    Args:
        publisher: ZeroMQ publisher socket
        metadata: Packed metadata
        frame_data: Encoded frame data

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        publisher.send_multipart([metadata, frame_data])
        logging.debug(f"Published frame with {len(frame_data)} bytes")
        return True
    except Exception as e:
        logging.error(f"Error publishing frame: {e}")
        return False


def send_frames(publisher, camera, imx500, state: ThreadSafeState):
    """Function for capturing and sending frames"""

    frame_count = 0

    while state["should_run"]:
        try:
            # Get frame from camera (this should be in camera_utils)
            local_frame = camera.capture_array()
            if local_frame is None:
                logging.error(f"Failed to capture frame {frame_count}")
                time.sleep(0.5)
                continue

            logging.debug(
                f"Captured frame {frame_count} with shape: {local_frame.shape}"
            )

            # Get people count (this should be in camera_utils)
            metadata = camera.capture_metadata()
            people_count = get_num_people_local(metadata, imx500)

            # Update state
            state["local_num_people"] = people_count

            # Encode frame
            frame_data = encode_frame(local_frame)
            if frame_data is None:
                continue

            # Create metadata
            packed_metadata = create_frame_metadata(people_count)

            # Publish frame
            if publish_frame(publisher, packed_metadata, frame_data):
                logging.debug(f"Sent frame {frame_count}")
                frame_count += 1

            # Sleep to control frame rate
            time.sleep(0.033)  # ~30 FPS

        except Exception as e:
            logging.error(f"Error in send_frames: {e}")
            time.sleep(1)  # Short delay before retry


# ---------------------- Receive Frame Functions ----------------------


def receive_message(subscriber):
    """
    Receive a message from the subscriber

    Args:
        subscriber: ZeroMQ subscriber socket

    Returns:
        tuple: (packed_metadata, frame_data) or (None, None) if failed
    """
    try:
        message_parts = subscriber.recv_multipart()
        logging.debug(f"Received message with {len(message_parts)} parts")

        if len(message_parts) == 2:
            return message_parts[0], message_parts[1]
        else:
            logging.warning(f"Unexpected message format: {len(message_parts)} parts")
            return None, None

    except zmq.ZMQError as e:
        if e.errno == zmq.EAGAIN:
            logging.debug("Timeout waiting for message")
        else:
            logging.error(f"ZMQ error receiving message: {e}")
        return None, None
    except Exception as e:
        logging.error(f"Error receiving message: {e}")
        return None, None


def unpack_metadata(packed_metadata):
    """
    Unpack metadata from a received message

    Args:
        packed_metadata: Packed metadata bytes

    Returns:
        dict: Unpacked metadata or empty dict if failed
    """
    try:
        metadata = msgpack.unpackb(packed_metadata)
        logging.debug(f"Unpacked metadata: {metadata}")
        return metadata
    except Exception as e:
        logging.error(f"Error unpacking metadata: {e}")
        return {}


def decode_frame(frame_data):
    """
    Decode a frame from received data

    Args:
        frame_data: Encoded frame data

    Returns:
        numpy.ndarray: Decoded frame or None if failed
    """
    try:
        frame = cv2.imdecode(
            np.frombuffer(frame_data, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if frame is not None:
            logging.debug(f"Decoded frame with shape: {frame.shape}")
        else:
            logging.warning("Frame decoded as None")
        return frame
    except Exception as e:
        logging.error(f"Error decoding frame: {e}")
        return None


def update_view_state(state, current_time):
    """
    Update the view state based on last received frame time

    Args:
        state: Application state
        current_time: Current time

    Returns:
        bool: True if view was switched, False otherwise
    """
    last_frame_time = state.get("last_remote_frame_time", 0)

    if current_time - last_frame_time > 3:
        state["display_local"] = True
        logging.info("Switched to local view due to timeout")
        return True
    return False


def receive_frames(subscriber, state: ThreadSafeState):
    """Function for receiving frames"""
    while state["should_run"]:
        try:
            # Receive message
            packed_metadata, frame_data = receive_message(subscriber)
            if packed_metadata is None:
                # Check if we should switch to local view
                update_view_state(state, time.time())
                continue

            # Unpack metadata
            metadata = unpack_metadata(packed_metadata)
            remote_people_count = metadata.get("people_count", 0)

            # Decode frame
            frame = decode_frame(frame_data)
            if frame is None:
                continue

            # Update state
            with state.lock:
                state["remote_frame"] = frame
                state["remote_num_people"] = remote_people_count
                state["last_remote_frame_time"] = time.time()
                state["display_local"] = False  # Switch to remote view

            logging.info(
                f"Updated state with remote frame, {remote_people_count} people"
            )

        except Exception as e:
            logging.error(f"Error in receive_frames: {e}")
            time.sleep(0.5)  # Short delay before retry
