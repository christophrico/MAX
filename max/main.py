import cv2
import zmq
import time
import threading
import logging
import configparser
import signal
import multiprocessing as mp
import os

from camera_utils import init_camera, get_frame_for_display
from network_utils import (
    init_connection,
    init_publisher,
    init_subscriber,
    send_frames,
    receive_frames,
)
from led_utils import led_control_process

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
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logging.info(f"Received signal {signum}, shutting down...")
    app_state["should_run"] = False

def display_frames(camera, state):
    """Function for displaying frames"""
    
    cv2.namedWindow('image')
    cv2.moveWindow('image', 200, 200)
    
    while state["should_run"]:
        try:
            # Get the appropriate frame for display
            frame = get_frame_for_display(camera, state)

            if frame is None:
                logging.warning("No frame available for display")
                time.sleep(0.1)
                continue
   
            resized_frame = cv2.resize(frame, (191, 191))

            # Display the frame
            cv2.imshow("image", resized_frame)

            # Exit on 'q' key
            key = cv2.waitKey(1)
            if key == ord("q"):
                state["should_run"] = False
                logging.info("User pressed 'q', stopping application")

        except Exception as e:
            logging.error(f"Error in display_frames: {e}")
            time.sleep(0.5)

def cleanup(zmq_context, publisher, subscriber, led_process=None):
    """Cleanup function to release resources"""
    logging.info("Starting cleanup...")
    
    # Stop LED process - try to terminate gracefully first
    if led_process:
        try:
            if led_process.is_alive():
                logging.info("Stopping LED process...")
                led_process.terminate()  # Graceful termination
                led_process.join(timeout=3)  # Wait up to 3 seconds
                
                if led_process.is_alive():
                    logging.warning("LED process didn't stop gracefully, force killing...")
                    led_process.kill()  # Force kill
                    led_process.join(timeout=1)
                    
                logging.info("LED process stopped")
        except Exception as e:
            logging.warning(f"Error stopping LED process: {e}")
    
    # Also try to kill any remaining LED processes by name (in case of restarts)
    try:
        import subprocess
        result = subprocess.run(['pkill', '-f', 'led_control_process'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logging.info("Cleaned up any remaining LED processes")
    except Exception as e:
        logging.debug(f"Could not cleanup LED processes by name: {e}")
    
    try:
        cv2.destroyAllWindows()
        logging.info("OpenCV windows destroyed")
    except Exception as e:
        logging.warning(f"Error destroying OpenCV windows: {e}")
    
    try:
        if publisher:
            publisher.close()
            logging.info("Publisher closed")
    except Exception as e:
        logging.warning(f"Error closing publisher: {e}")
    
    try:
        if subscriber:
            subscriber.close()
            logging.info("Subscriber closed")
    except Exception as e:
        logging.warning(f"Error closing subscriber: {e}")
    
    try:
        if zmq_context:
            zmq_context.term()
            logging.info("ZMQ context terminated")
    except Exception as e:
        logging.warning(f"Error terminating ZMQ context: {e}")

def monitor_led_process(led_process, led_queue, restart_queue):
    """Monitor LED process and restart if it crashes"""
    current_process = led_process
    
    while app_state["should_run"]:
        try:
            if not current_process.is_alive():
                logging.warning("LED process died, attempting restart...")
                
                # Start new LED process
                new_process = mp.Process(
                    target=led_control_process,
                    args=(led_queue, restart_queue),
                    name="LEDProcess"
                )
                new_process.start()
                
                # Send restart notification
                try:
                    restart_info = {
                        'new_pid': new_process.pid,
                        'restart_time': time.time()
                    }
                    restart_queue.put_nowait(restart_info)
                    logging.info(f"LED process restarted with new PID: {new_process.pid}")
                except Exception as e:
                    logging.warning(f"Could not send restart notification: {e}")
                
                # IMPORTANT: Re-activate LEDs after restart
                time.sleep(0.5)  # Give process time to initialize
                send_led_command(led_queue, {'type': 'set_all_active', 'active': True})
                logging.info("Re-activated LEDs after restart")
                
                # Send current people count to new process
                current_people = app_state.get("local_num_people", 0)
                send_led_command(led_queue, {'type': 'set_people_count', 'count': current_people})
                
                # Update our reference and continue monitoring the new process
                current_process = new_process
                
            time.sleep(1)  # Check every second
        except Exception as e:
            logging.error(f"Error in LED process monitor: {e}")
            time.sleep(1)

def send_led_command(led_queue, command):
    """Send command to LED process (non-blocking)"""
    try:
        led_queue.put_nowait(command)
        logging.debug(f"Sent LED command: {command}")
    except:
        logging.warning("LED command queue full - command dropped")

def main():
    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    camera = None
    imx500 = None
    zmq_context = None
    publisher = None
    led_process = None
    subscriber = None

    try:
        logging.info("Starting MAX application...")
        
        # Load configuration
        config = configparser.ConfigParser()
        config.read("config.ini")

        # Initialize camera BEFORE setting up multiprocessing
        logging.info("Initializing camera...")
        camera, imx500 = init_camera()

        # NOW set up multiprocessing for LED process
        # (after camera is initialized to avoid conflicts)
        try:
            mp.set_start_method('fork')  # Use fork instead of spawn
        except RuntimeError:
            # Start method already set, that's OK
            pass

        # Initialize ZeroMQ
        logging.info("Initializing ZeroMQ...")
        zmq_context = init_connection()
        publisher = init_publisher(zmq_context, config)

        # Video streaming threads
        send_thread = threading.Thread(
            target=send_frames,
            args=(publisher, camera, imx500, app_state),
            name="SendFrames",
            daemon=True,
        )
        
        # Update the receive_thread creation:
        receive_thread = threading.Thread(
            target=receive_frames, 
            args=(app_state, zmq_context, config),  # Pass zmq_context and config
            name="ReceiveFrames",
            daemon=True
        )
        
        display_thread = threading.Thread(
            target=display_frames, 
            args=(camera, app_state), 
            name="DisplayFrames",
            daemon=True
        )

        # LED Process setup (separate from threads)
        led_queue = mp.Queue(maxsize=50)  # Multiprocessing queue
        restart_queue = mp.Queue(maxsize=5)  # For process restart communication
        
        led_process = mp.Process(
            target=led_control_process,
            args=(led_queue, restart_queue),
            name="LEDProcess"
        )

        # Start LED process
        led_process.start()
        logging.info(f"Started LED process with PID: {led_process.pid}")

        # Start LED process monitor thread (but don't start it manually)
        monitor_thread = threading.Thread(
            target=monitor_led_process,
            args=(led_process, led_queue, restart_queue),
            name="LEDMonitor",
            daemon=True
        )

        # Start all threads together
        threads = [send_thread, receive_thread, display_thread, monitor_thread]
        for thread in threads:
            thread.start()
            logging.info(f"Started thread: {thread.name}")

        # Initialize LEDs - they'll start with default animations
        time.sleep(1)  # Give LED process time to start
        send_led_command(led_queue, {'type': 'set_all_active', 'active': True})
        logging.info("Sent initial LED activation command")

        logging.info("All threads and processes started")

        # Main monitoring loop
        last_people_update = 0
        people_update_interval = 5  # Only update people count every 5 seconds
        
        while app_state["should_run"]:
            try:
                current_time = time.time()
                
                # Check for LED process restarts
                try:
                    restart_info = restart_queue.get_nowait()
                    new_pid = restart_info.get('new_pid')
                    logging.info(f"Received LED process restart notification: PID {new_pid}")
                    # Note: We can't update led_process reference easily since monitor has it
                    # But that's OK - the monitor will handle the new process
                except:
                    pass  # No restart messages
                
                # Check if ZMQ context is still valid
                if zmq_context.closed:
                    logging.error("ZMQ context was closed externally!")
                    app_state["should_run"] = False
                    break
                    
                # Update LED with people count - but not too frequently
                if current_time - last_people_update > people_update_interval:
                    current_people = app_state.get("local_num_people", 0)
                    send_led_command(led_queue, {'type': 'set_people_count', 'count': current_people})
                    last_people_update = current_time
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logging.error(f"Error in main monitoring loop: {e}")
                time.sleep(1)

        logging.info("Main loop exiting...")

    except Exception as e:
        logging.error(f"Fatal error in main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Signal all threads to stop
        app_state["should_run"] = False
        
        # Turn off LEDs before shutdown
        if led_process and led_process.is_alive():
            send_led_command(led_queue, {'type': 'turn_off_all'})
            time.sleep(0.5)  # Give time for LEDs to turn off
        
        # Wait a moment for threads to stop
        logging.info("Waiting for threads to stop...")
        time.sleep(2)

        # Clean up resources (this will also stop the LED process)
        cleanup(zmq_context, publisher, subscriber, led_process)
        
        logging.info("Application shutdown complete")

if __name__ == "__main__":
    main()