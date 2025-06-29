#!/bin/bash

# Function to display messages in terminal
display() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Function to wait for litebeam connection
wait_for_litebeam() {
    local litebeam_ip="172.16.0.4"
    
    display "Waiting for litebeam connection at $litebeam_ip..."
    
    while true; do
        if ping -c 1 -W 3 "$litebeam_ip" >/dev/null 2>&1; then
            display "✓ Litebeam connection established!"
            break
        else
            display "Waiting for litebeam... (retrying in 5 seconds)"
            sleep 5
        fi
    done
}

display "Starting MAX application..."

# Wait for litebeam connection
wait_for_litebeam

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

# Run the Python program using Poetry
display "Starting Python program: main.py"
poetry run python3 main.py