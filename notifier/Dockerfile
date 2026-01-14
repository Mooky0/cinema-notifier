FROM alpine:latest

WORKDIR /app

# 1. Install system dependencies
RUN apk add --no-cache python3 py3-pip

# 2. Copy requirements first (better for Docker caching)
COPY requirements.txt .

# 3. Install packages using the bypass flag
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# 4. Copy the rest of your code
COPY . .

CMD ["python3", "main.py"]