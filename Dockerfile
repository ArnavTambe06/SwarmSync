FROM python:3.11-slim
WORKDIR /app
COPY swarm ./swarm
COPY web ./web
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV SWARMSYNC_HOST=0.0.0.0 SWARMSYNC_PORT=8000
EXPOSE 8000
CMD ["python", "-m", "swarm.server"]
