# MAX
A distributed video chat system using Raspberry Pi cameras with person detection capabilities.

## Setup Instructions

### 1. Hardware Requirements

- 2 Raspberry Pi devices (Raspberry Pi 4 or newer recommended)
- Raspberry Pi cameras for each device
- Both devices connected to the same network

### 2. Software Dependencies



### 3. Configuration

Create a `config.ini` file on both devices:

#### Device A Configuration

```ini
[LOCAL]
port = 5555  # Device A publishes on port 5555

[REMOTE]
ip = 192.168.1.XXX  # IP address of Device B
port = 5556  # Device B publishes on port 5556

[CAMERA]
model = /path/to/model
height = 480
width = 640
iou = 0.45
threshold = 0.5
max_detections = 10
inference_rate = 10
```

#### Device B Configuration

```ini
[LOCAL]
port = 5556  # Device B publishes on port 5556

[REMOTE]
ip = 192.168.1.YYY  # IP address of Device A
port = 5555  # Device A publishes on port 5555

[CAMERA]
model = /path/to/model
height = 480
width = 640
iou = 0.45
threshold = 0.5
max_detections = 10
inference_rate = 10
```

## Usage

### 0. Prerequisites

```bash
cd MAX/max
poetry shell
```

### 1. Run Network Diagnostics

Before starting the video chat, run the network diagnostics to ensure connectivity:

```bash

python3 launcher.py diagnose
```

### 2. Test Network Connectivity

Test the ZeroMQ connection between devices:

```bash
python3 launcher.py test
```

### 3. Start the Video Chat

Start the main application:

```bash
python3 launcher.py app
```

Or simply:

```bash
python3 launcher.py
```

## Troubleshooting

### Network Connectivity Issues

If you're experiencing connectivity issues:

1. Run the diagnostics to check network configuration:
   ```bash
   python launcher.py diagnose
   ```

2. Ensure both devices can ping each other.

3. Verify that the ports are not blocked by a firewall.

4. Check that the IP addresses in the configuration files are correct.

### Video Streaming Issues

If video streaming is not working:

1. Run the network test to verify basic message passing:
   ```bash
   python launcher.py test
   ```

2. Enable debug logging for more detailed information:
   ```bash
   python launcher.py app --debug
   ```

3. Check the camera module connections and permissions.

## Architecture Details

### Key Components

- **ThreadSafeState**: Thread-safe container for shared application state
- **ZeroMQ PUB/SUB**: Messaging pattern for video streaming
- **IMX500 Processor**: Hardware acceleration for person detection

### File Structure

- `main.py`: Main application entry point
- `network_utils.py`: ZeroMQ networking functions
- `camera_utils.py`: Camera and person detection utilities
- `state_class.py`: Thread-safe state management
- `network_test.py`: Network connectivity test
- `diagnostics.py`: Network diagnostics utilities
- `launcher.py`: Unified command interface

## License

This project is licensed under the MIT License - see the LICENSE file for details.