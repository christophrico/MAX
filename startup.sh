#!/bin/bash

# Function to display messages in terminal
display() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

display "Starting MAX application..."

# Change to the project directory
PROJECT_DIR="$HOME/Documents/MAX/max"
if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
    display "Changed to directory: $PROJECT_DIR"
else
    display "ERROR: Directory $PROJECT_DIR does not exist"
    sleep 10
    exit 1
fi

# Wait for network connection
display "Waiting for network connection..."
MAX_ATTEMPTS=100
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if ping -c 1 -W 1 8.8.8.8 > /dev/null 2>&1; then
        IP_ADDRESS=$(hostname -I | awk '{print $1}')
        display "Network is up. IP address: $IP_ADDRESS"
        break
    fi
    
    ATTEMPT=$((ATTEMPT + 1))
    display "Waiting for network... attempt $ATTEMPT of $MAX_ATTEMPTS"
    sleep 5
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    display "ERROR: Network connection not available after $MAX_ATTEMPTS attempts"
    sleep 10
    exit 1
fi


# Run the Python program using Poetry
display "Starting Python program: main.py"
poetry run python3 main.py