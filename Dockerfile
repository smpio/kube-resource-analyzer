ARG PYTHON_IMAGE=python:3.9
FROM ${PYTHON_IMAGE}

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DEV_ENV=no
ENTRYPOINT ["./manage.py"]
