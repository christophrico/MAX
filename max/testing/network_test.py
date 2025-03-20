import zmq
import configparser
import time
import msgpack
import threading
import logging
import argparse
from state_class import ThreadSafeState


def test_connection(config_path="config.ini", debug=False):
    """Test ZeroMQ connection between publisher and subscriber"""
    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Shared state
    state = ThreadSafeState(
        {"running": True, "sent_count": 0, "received_count": 0, "last_received_time": 0}
    )

    # Load configuration
    config = configparser.ConfigParser()
    config.read(config_path)

    remote_ip = config["REMOTE"]["ip"]
    remote_port = int(config["REMOTE"]["port"])
    local_port = int(config["LOCAL"]["port"])

    logging.info("Testing connection with:")
    logging.info(f"Local port: {local_port}")
    logging.info(f"Remote IP: {remote_ip}")
    logging.info(f"Remote port: {remote_port}")

    # Initialize ZeroMQ context
    context = zmq.Context()

    # Create publisher socket
    publisher = context.socket(zmq.PUB)
    publisher.bind(f"tcp://*:{local_port}")
    logging.info(f"Publisher bound to port {local_port}")

    # Create subscriber socket
    subscriber = context.socket(zmq.SUB)
    subscriber.connect(f"tcp://{remote_ip}:{remote_port}")
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all messages
    subscriber.setsockopt(zmq.RCVTIMEO, 5000)  # 5000ms timeout
    logging.info(f"Subscriber connected to {remote_ip}:{remote_port}")

    # Allow time for connection to establish
    logging.info("Waiting for connection to establish...")
    time.sleep(2)  # ZeroMQ connections need a moment to initialize

    # Function to send test messages
    def send_test_messages():
        while state["running"]:
            try:
                message_count = state["sent_count"]
                test_message = msgpack.packb(
                    {
                        "type": "test",
                        "message": f"Test message {message_count}",
                        "timestamp": time.time(),
                    }
                )
                publisher.send(test_message)
                logging.info(f"Sent test message {message_count}")
                state["sent_count"] = message_count + 1
                time.sleep(1)
            except Exception as e:
                logging.error(f"Error sending test message: {e}")
                time.sleep(1)

    # Function to receive test messages
    def receive_test_messages():
        while state["running"]:
            try:
                message = subscriber.recv()
                try:
                    data = msgpack.unpackb(message)
                    state["last_received_time"] = time.time()
                    state["received_count"] = state["received_count"] + 1
                    logging.info(f"Received message: {data}")
                except Exception as e:
                    logging.error(f"Error unpacking message: {e}")
            except zmq.ZMQError as e:
                if e.errno == zmq.EAGAIN:
                    logging.debug("Timeout waiting for message")
                else:
                    logging.error(f"ZMQ error: {e}")
            except Exception as e:
                logging.error(f"Error receiving message: {e}")
                time.sleep(0.5)

    # Function to monitor connection status
    def monitor_connection():
        last_report_time = time.time()
        last_received_count = 0

        while state["running"]:
            # Report status every 5 seconds
            current_time = time.time()
            if current_time - last_report_time >= 5:
                received_count = state["received_count"]
                messages_since_last = received_count - last_received_count

                logging.info(
                    f"Status: Sent {state['sent_count']} messages, Received {received_count} messages"
                )
                logging.info(
                    f"Messages received in last 5 seconds: {messages_since_last}"
                )

                if messages_since_last == 0:
                    last_received_time = state["last_received_time"]
                    if last_received_time > 0:
                        time_since_last = current_time - last_received_time
                        logging.warning(
                            f"No messages received in last 5 seconds. Time since last message: {time_since_last:.2f}s"
                        )
                    else:
                        logging.warning("No messages received yet")

                last_report_time = current_time
                last_received_count = received_count

            time.sleep(1)

    # Start threads
    sender_thread = threading.Thread(target=send_test_messages)
    receiver_thread = threading.Thread(target=receive_test_messages)
    monitor_thread = threading.Thread(target=monitor_connection)

    sender_thread.start()
    receiver_thread.start()
    monitor_thread.start()

    try:
        logging.info("Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping test...")
        state["running"] = False

    # Wait for threads to finish
    sender_thread.join(timeout=2)
    receiver_thread.join(timeout=2)
    monitor_thread.join(timeout=2)

    # Clean up
    publisher.close()
    subscriber.close()
    context.term()

    # Report final statistics
    logging.info("Test complete")
    logging.info(f"Total messages sent: {state['sent_count']}")
    logging.info(f"Total messages received: {state['received_count']}")

    # Determine if test was successful
    success = state["received_count"] > 0
    logging.info(f"Connection test {'PASSED' if success else 'FAILED'}")
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ZeroMQ networking connection")
    parser.add_argument("--config", default="config.ini", help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    test_connection(args.config, args.debug)
