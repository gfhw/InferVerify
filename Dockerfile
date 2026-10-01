FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY inferverify/ inferverify/
COPY tests/ tests/

# kopf runs the operator; --all-namespaces so it watches every namespace.
CMD ["kopf", "run", "-m", "inferverify.main", "--all-namespaces"]
