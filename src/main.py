import json

import kopf
import logging
import os

import pykube
import yaml
import kubernetes
from kubernetes.client import ApiException


def generate_certificate(hostname, service_name):
    ssl_config = open("openssl_conf").read()

    f = open(f"./openssl-{service_name}.cnf", "a")
    f.write(ssl_config.format(hostname=hostname, service_name=service_name))
    f.close()

    os.system(f"openssl req -x509 -config ./openssl-{service_name}.cnf -nodes -days 365 -newkey rsa:2048 -keyout "
              f"./web-{service_name}.key -out ./web-{service_name}.crt")

    os.system("cat ./web-" + service_name + ".key | base64 -w 0 > ./web-" + service_name + ".key.b64")
    os.system("cat ./web-" + service_name + ".crt | base64 -w 0 > ./web-" + service_name + ".crt.b64")
    key = open("./web-" + service_name + ".key.b64").read()
    cert = open("./web-" + service_name + ".crt.b64").read()
    os.remove("./web-" + service_name + ".crt")
    os.remove("./web-" + service_name + ".key")
    os.remove("./web-" + service_name + ".crt.b64")
    os.remove("./web-" + service_name + ".key.b64")
    os.remove("./openssl-" + service_name + ".cnf")
    return key, cert


def create_certificate(hostname, claim_name, namespace, service_name, secret_name):
    key, cert = generate_certificate(hostname, service_name)
    secrets = open("secret.yaml", 'rt').read()
    return secrets.format(secret_name=secret_name, key=key, cert=cert, claim=claim_name, namespace=namespace)


def secret_exists(secret_name, namespace):
    try:
        api = kubernetes.client.CoreV1Api()
        api.read_namespaced_secret(name=secret_name, namespace=namespace)
    except ApiException as exc:
        if exc.reason == "Not Found":
            return False
    return True


@kopf.on.create('certificategenerationclaims')
def create_cgc_fn(body, **kwargs):
    api = kubernetes.client.CoreV1Api()
    claim_name = body['metadata']['name']
    namespace = body['metadata']['namespace']
    hostname = body['spec']['host']
    service_namespace = f"{claim_name}-{namespace}"
    secret_name = f"cgc-{claim_name}"

    if not secret_exists(secret_name, namespace):
        yaml_text = create_certificate(hostname, claim_name, namespace, service_namespace, secret_name)

        logging.info(f"generate new certificate: {claim_name} in {namespace}")
        data = yaml.safe_load(yaml_text)

        kopf.adopt(data)

        obj = api.create_namespaced_secret(
            namespace=namespace,
            body=data,
        )
        return {'secret-name': obj.metadata.name}


@kopf.on.resume('certificategenerationclaims')
def resume_cgc_fn(body, **kwargs):
    api = kubernetes.client.CoreV1Api()
    claim_name = body['metadata']['name']
    namespace = body['metadata']['namespace']
    service_namespace = f"{claim_name}-{namespace}"
    secret_name = f"cgc-{claim_name}"
    hostname = body['spec']['host']

    if not secret_exists(secret_name, namespace):
        yaml_text = create_certificate(hostname, claim_name, namespace, service_namespace, secret_name)

        logging.info(f"generate new certificate: {claim_name} in {namespace}")
        data = yaml.safe_load(yaml_text)

        kopf.adopt(data)

        obj = api.create_namespaced_secret(
            namespace=namespace,
            body=data,
        )
        return {'secret-name': obj.metadata.name}


@kopf.on.create('deployment', annotations={'cgc': kopf.PRESENT})
async def create_deployment_fn(body, **kwargs):


    namespace = body['metadata']['namespace']
    deployment_name = body['metadata']['name']
    cgc_name = body['metadata']['annotations']['cgc']
    service_namespace = f"{cgc_name}-{namespace}"
    secret_name = f"cgc-{cgc_name}"

    v1api = pykube.HTTPClient(pykube.KubeConfig.from_env())
    manifest = pykube.Deployment.objects(v1api).get_by_name(deployment_name)

    if not secret_exists(secret_name, namespace):
        raise kopf.TemporaryError("The CGC Secret is not created yet.", delay=15)

    print(f"{cgc_name} certificate for deployment {deployment_name} in {namespace}")

    for container in manifest.obj['spec']['template']['spec']['containers']:
        if 'volumeMounts' not in container:
            container['volumeMounts'] = []
        else:
            for vol in container['volumeMounts']:
                if vol['name'] == f"key-{cgc_name}":
                    print(f"{deployment_name} already setup for CGC secrets")
                    return
        container['volumeMounts'].append(
            {
                "name": f"key-{cgc_name}",
                "mountPath": "/web/key/"
            }
        )
        container['volumeMounts'].append(
            {
                "name": f"cert-{cgc_name}",
                "mountPath": "/web/cert/"
            }
        )


    manifest.obj['spec']['template']['spec']['volumes'] = [
        {
            "name": f"key-{cgc_name}",
            "secret": {
                "secretName": secret_name,
                "items": [
                    {
                        "key": "key",
                        "path": f"{cgc_name}.key"
                    }
                ]
            }
        },
        {
            "name": f"cert-{cgc_name}",
            "secret": {
                "secretName": secret_name,
                "items": [
                    {
                        "key": "cert",
                        "path": f"{cgc_name}.crt"
                    }
                ]
            }
        }
    ]

    manifest.update()


@kopf.on.resume('deployment', annotations={'cgc': kopf.PRESENT})
async def resume_deployment_fn(body, **kwargs):

    namespace = body['metadata']['namespace']
    deployment_name = body['metadata']['name']
    cgc_name = body['metadata']['annotations']['cgc']
    service_namespace = f"{cgc_name}-{namespace}"
    secret_name = f"cgc-{cgc_name}"

    v1api = pykube.HTTPClient(pykube.KubeConfig.from_env())
    manifest = pykube.Deployment.objects(v1api).get_by_name(deployment_name)

    if not secret_exists(secret_name, namespace):
        raise kopf.TemporaryError("The CGC Secret is not created yet.", delay=15)

    print(f"{cgc_name} certificate for deployment {deployment_name} in {namespace}")

    for container in manifest.obj['spec']['template']['spec']['containers']:
        if 'volumeMounts' not in container:
            container['volumeMounts'] = []
        else:
            for vol in container['volumeMounts']:
                if vol['name'] == f"key-{cgc_name}":
                    print(f"{deployment_name} already setup for CGC secrets")
                    return
        container['volumeMounts'].append(
            {
                "name": f"key-{cgc_name}",
                "mountPath": "/web/key/"
            }
        )
        container['volumeMounts'].append(
            {
                "name": f"cert-{cgc_name}",
                "mountPath": "/web/cert/"
            }
        )

    manifest.obj['spec']['template']['spec']['volumes'] = [
        {
            "name": f"key-{cgc_name}",
            "secret": {
                "secretName": secret_name,
                "items": [
                    {
                        "key": "key",
                        "path": f"{cgc_name}.key"
                    }
                ]
            }
        },
        {
            "name": f"cert-{cgc_name}",
            "secret": {
                "secretName": secret_name,
                "items": [
                    {
                        "key": "cert",
                        "path": f"{cgc_name}.crt"
                    }
                ]
            }
        }
    ]

    manifest.update()
