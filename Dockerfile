ARG PYTHON_IMAGE=python:3.14.7
FROM ${PYTHON_IMAGE}

WORKDIR /usr/src/app

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

ENV DEV_ENV=no
ENTRYPOINT ["./manage.py"]
