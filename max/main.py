import configparser

import cv2
from camera_utils import get_num_people_local, init_camera
from network_utils import init_connection, receive_frame, send_frame

config = configparser.ConfigParser()
config.read("config.ini")

# State Variables
DISPLAY_LOCAL = False
LOCAL_NUM_PEOPLE = 0
REMOTE_NUM_PEOPLE = 0
PICAM2 = None
IMX500 = None
OUTGOING_SOCKET = None
INCOMING_CONNECTION = None


def main():
    PICAM2, IMX500 = init_camera()
    OUTGOING_SOCKET, INCOMING_CONNECTION = init_connection()

    while True:
        # get the local image stream
        local_frame = PICAM2.capture_array()
        # parse the number of people in frame
        metadata = PICAM2.capture_metadata()
        LOCAL_NUM_PEOPLE = get_num_people_local(metadata, IMX500)

        # send the frame and the number of people to the remote
        send_frame(OUTGOING_SOCKET, local_frame, LOCAL_NUM_PEOPLE)
        # receive the frame and the number of people from the remote
        remote_frame, REMOTE_NUM_PEOPLE = receive_frame(INCOMING_CONNECTION)

        if DISPLAY_LOCAL:
            frame = local_frame
        else:
            frame = remote_frame

        cv2.imshow("f", frame)
        cv2.waitKey(1)


if __name__ == "__main__":
    main()
