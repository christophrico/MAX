import cv2
import zmq
import time
import threading
import logging
import configparser
import queue

from camera_utils import init_camera, get_frame_for_display
from network_utils import (
    init_connection,
    init_publisher,
    init_subscriber,
    send_frames,
    receive_frames,
)
from state_class import ThreadSafeState

# Initialize the thread-safe state
app_state = ThreadSafeState(
    {
        "should_run": True,
        "display_local": True,
        "local_num_people": 0,
        "remote_num_people": 0,
        "last_remote_frame_time": 0,
        "remote_frame": None,
    }
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Communication queues for different subsystems
led_queue = queue.Queue()


def display_frames(camera, state):
    """Function for displaying frames"""
    while state["should_run"]:
        try:
            # Get the appropriate frame for display
            frame = get_frame_for_display(camera, state)

            if frame is None:
                logging.warning("No frame available for display")
                time.sleep(0.1)
                continue

            # Display the frame
            cv2.imshow("Video Stream", frame)

            # Exit on 'q' key
            key = cv2.waitKey(1)
            if key == ord("q"):
                state["should_run"] = False
                logging.info("User pressed 'q', stopping application")

        except Exception as e:
            logging.error(f"Error in display_frames: {e}")
            time.sleep(0.5)  # Short delay before retry


def cleanup(zmq_context, publisher, subscriber):
    """Cleanup function to release resources"""
    cv2.destroyAllWindows()
    publisher.close()
    subscriber.close()
    zmq_context.term()
    logging.info("Application stopped")


def main():
    try:
        # Load configuration
        config = configparser.ConfigParser()
        config.read("config.ini")

        # Initialize camera
        camera, imx500 = init_camera()

        # Initialize ZeroMQ
        zmq_context = init_connection()
        publisher = init_publisher(zmq_context, config)
        subscriber = init_subscriber(zmq_context, config)

        # Start threads
        threads = []

        # Video streaming threads
        threads.append(
            threading.Thread(
                target=send_frames,
                args=(publisher, camera, imx500, app_state),
                daemon=True,
            )
        )
        threads.append(
            threading.Thread(
                target=receive_frames, args=(subscriber, app_state), daemon=True
            )
        )
        threads.append(
            threading.Thread(
                target=display_frames, args=(camera, app_state), daemon=True
            )
        )

        # Start all threads
        for thread in threads:
            thread.start()

        logging.info("All threads started")

        # Keep the main thread alive
        while app_state["should_run"]:
            time.sleep(0.5)

    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        app_state["should_run"] = False
    finally:
        # Allow time for threads to notice the stop signal
        time.sleep(1)

        # Clean up resources
        cleanup(zmq_context, publisher, subscriber)


if __name__ == "__main__":
    main()
