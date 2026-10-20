FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pymysql paramiko "psycopg[binary]" oracledb pymssql
COPY app.py carico.py frasi.py demo_meridia.py index.html .
COPY fonts ./fonts
EXPOSE 8091
CMD ["python", "-u", "app.py"]
