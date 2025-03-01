import socket
import struct
import msgpack
import cv2
import numpy as np

# Set up the socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind(("192.168.68.54", 10001))
server_socket.listen(1)

# Accept a connection
conn, addr = server_socket.accept()
print("Connection from:", addr)

while True:
    try:
        # Step 1: Receive the length of the incoming message
        data_size = conn.recv(4)
        if not data_size:
            break

        # Unpack the length of the data
        msg_len = struct.unpack("I", data_size)[0]

        # Step 2: Receive the actual data based on the received message length
        data = b""
        while len(data) < msg_len:
            packet = conn.recv(msg_len - len(data))
            if not packet:
                break
            data += packet

        # Step 3: Unpack the received data using msgpack
        unpacked_data = msgpack.unpackb(data, raw=False)
        frame_data = unpacked_data["frame"]
        number_of_persons = unpacked_data["number_of_persons"]

        # Decode the image from JPEG format back to a NumPy array
        frame = cv2.imdecode(
            np.frombuffer(frame_data, dtype=np.uint8), cv2.IMREAD_COLOR
        )

        # Display the frame
        cv2.imshow("Received Frame", frame)
        print("Number of persons detected:", number_of_persons)

        # Exit loop if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    except Exception as e:
        print("Error:", e)
        break

# Cleanup
conn.close()
server_socket.close()
cv2.destroyAllWindows()