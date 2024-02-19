FROM python:3.11-buster

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    libasound-dev \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev -y \
    && rm -rf /var/lib/apt/lists/*

COPY pip.conf /etc/pip.conf

WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt

EXPOSE 8000

# Set the entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
