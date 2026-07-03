#!/bin/bash

# Navigate to the project root directory where this script is located
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Virtual environment 'venv' not found. Please set up the environment first."
    exit 1
fi

# Activate the virtual environment
source venv/bin/activate

# Execute the python script, passing through any arguments
python scripts/bootstrap_facebook_session.py "$@"
