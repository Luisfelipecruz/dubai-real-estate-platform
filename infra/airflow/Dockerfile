FROM apache/airflow:2.10.4-python3.12

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev default-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr
ENV SPARK_HOME=/home/airflow/.local/lib/python3.12/site-packages/pyspark

USER airflow

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Download PostgreSQL JDBC driver for Spark jobs
RUN curl -fSL https://jdbc.postgresql.org/download/postgresql-42.7.4.jar \
    -o ${SPARK_HOME}/jars/postgresql-42.7.4.jar

COPY entrypoint.sh /entrypoint.sh
