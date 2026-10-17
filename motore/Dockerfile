FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pymysql
COPY app.py demo_meridia.py index.html .
EXPOSE 8091
CMD ["python", "-u", "app.py"]
