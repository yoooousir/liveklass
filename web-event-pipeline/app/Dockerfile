FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성 (Matplotlib 폰트 렌더링)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpng-dev \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generator.py  .
COPY analytics.py  .
COPY entrypoints.sh .
RUN chmod +x entrypoints.sh

ENTRYPOINT ["./entrypoints.sh"]
