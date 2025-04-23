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




# Run the Python program using Poetry
display "Starting Python program: main.py"
poetry run python3 main.py
