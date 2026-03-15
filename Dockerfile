# 1. Use a lightweight Python version
FROM python:3.12-slim

# 2. Set the directory inside the container
WORKDIR /app

# 3. Copy the list of libraries and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy your code into the container
COPY . .

# 5. Start the app using Gunicorn on the port Google provides
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app