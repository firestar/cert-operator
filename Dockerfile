FROM python:3.7
ADD src/ /src
RUN pip install kopf pykube-ng kubernetes PyYAML
WORKDIR /src
CMD kopf run main.py