FROM apache/spark:3.5.4-python3

USER root

# Install Python dependencies for PySpark jobs
RUN pip install --no-cache-dir psycopg2-binary==2.9.10 pytest==8.3.4

# Download PostgreSQL JDBC driver for Spark
RUN curl -fSL https://jdbc.postgresql.org/download/postgresql-42.7.4.jar \
    -o /opt/spark/jars/postgresql-42.7.4.jar

USER spark
