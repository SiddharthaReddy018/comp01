FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential make gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /comp01
COPY . .

# The human mounts the starter kit at /kit
ENV COMP01_KIT=/kit

CMD ["make", "test"]
