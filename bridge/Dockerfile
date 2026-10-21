FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests
# Build context is the repository root:
#   docker build -f bridge/Dockerfile -t dkv-bridge .
COPY custom_components/dkv_at_home/api.py custom_components/dkv_at_home/const.py /app/dkv_at_home/
COPY bridge/dkv_bridge.py /app/
ENV DKV_DATA_DIR=/data
VOLUME /data
EXPOSE 8099
CMD ["python", "dkv_bridge.py", "serve"]
