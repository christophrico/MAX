import argparse
import sys

import socket
import threading
import configparser
import struct
import msgpack

import cv2


from camera_utils import init_camera, get_num_people_local
from network_utils import init_connection, send_frame, receive_frame

config = configparser.ConfigParser()
config.read("config.ini")

# Global variables
REMOTE_IP = config["REMOTE"]["ip"]
REMOTE_PORT = int(config["REMOTE"]["port"])

DISPLAY_LOCAL = False


def main():
    PICAM2, IMX500 = init_camera()
    outgoing_socket, incoming_connection = init_connection()

    while True:
        # get the local image stream
        local_frame = PICAM2.capture_array()
        # parse the number of people in frame
        metadata = PICAM2.capture_metadata()
        num_persons = get_num_people_local(metadata, IMX500)  # type: ignore

        # send the frame and the number of people to the remote
        send_frame(outgoing_socket, local_frame, num_persons)
        # receive the frame and the number of people from the remote
        remote_frame, num_people = receive_frame(incoming_connection)

        if DISPLAY_LOCAL:
            frame = local_frame
        else:
            frame = remote_frame

        cv2.imshow("f", frame)  # type: ignore
        cv2.waitKey(1)


if __name__ == "__main__":
    main()
