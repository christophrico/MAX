import configparser
import socket
import struct
import time
import logging

import cv2
import msgpack
import numpy as np

config = configparser.ConfigParser()
config.read("config.ini")

remote_ip = config["REMOTE"]["ip"]
remote_port = int(config["REMOTE"]["port"])


def init_connection() -> tuple[socket.socket, socket.socket]:
    """
    Establishes a bidirectional socket connection. Retries until successful if the remote device is offline.
    """
    outgoing_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Keep trying to connect until successful
    while True:
        try:
            logging.info(f"Attempting to connect to {remote_ip}:{remote_port}...")
            outgoing_socket.connect((remote_ip, remote_port))
            logging.info("Outgoing connection established!")
            break  # Exit loop when successful
        except (socket.error, ConnectionRefusedError):
            logging.warning(
                f"Connection to {remote_ip}:{remote_port} failed. Retrying in 3 seconds..."
            )
            time.sleep(3)  # Wait before retrying

    # Setup incoming connection
    incoming_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    incoming_socket.bind(("0.0.0.0", remote_port))
    incoming_socket.listen(1)
    logging.info(f"Waiting for an incoming connection on port {remote_port}...")

    incoming_connection, addr = incoming_socket.accept()
    logging.info(f"Incoming connection established from {addr}!")

    return outgoing_socket, incoming_connection


def send_frame(
    outgoing_socket: socket.socket, frame: np.ndarray, number_of_persons: int
) -> None:
    # Encode the frame as JPEG
    _, frame_encoded = cv2.imencode(".jpg", frame)
    frame_data = frame_encoded.tobytes()

    payload = msgpack.packb(
        {"frame": frame_data, "number_of_persons": number_of_persons}, use_bin_type=True
    )

    # Send the size of the data and then the payload
    data_size = struct.pack("I", len(payload))
    outgoing_socket.sendall(data_size + payload)


def receive_frame(incoming_connection) -> tuple[np.ndarray, int]:
    try:
        # Receive the length of the incoming message
        data_size = incoming_connection.recv(4)
        if not data_size:
            return None

        # Unpack the length of the data
        msg_len = struct.unpack("I", data_size)[0]

        # Receive the actual data based on the received message length
        data = b""
        while len(data) < msg_len:
            packet = incoming_connection.recv(msg_len - len(data))
            if not packet:
                break
            data += packet

        # Unpack the received data using msgpack
        unpacked_data = msgpack.unpackb(data, raw=False)
        frame_data = unpacked_data["frame"]
        number_of_persons = unpacked_data["number_of_persons"]

        # Decode the image from JPEG format back to a NumPy array
        frame = cv2.imdecode(
            np.frombuffer(frame_data, dtype=np.uint8), cv2.IMREAD_COLOR
        )

    except Exception as e:
        print("Error:", e)
        return None

    return frame, number_of_persons
