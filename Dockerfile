FROM --platform=linux/arm64 python:3.12-slim
WORKDIR /app
COPY app.py auto_demo.py /app/
EXPOSE 8080
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/app.py"]
