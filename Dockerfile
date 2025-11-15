# Use an official Python runtime as a parent image
# We'll use a slim version for a smaller image size
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependegrncies needed for libraries like librosa (e.g., audio file processing)
# Although librosa primarily uses python libraries, this is a common best practice
# when dealing with scientific/audio processing libraries.
# Add the apt-get update/install/cleanup pattern for efficiency
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the working directory
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create the necessary directories
RUN mkdir -p uploads spectrograms model_spectrograms spectrograms_raw results static/bat_species

# Copy the rest of the application code
# Ensure models/predict.py exists in the source structure
COPY . .

# Expose the port the API runs on
EXPOSE 8000

# Command to run the application using Uvicorn
# We use 0.0.0.0 to make it accessible outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]