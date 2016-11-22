import pip
import os
import requests
import json
from cloudify import ctx
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError, RecoverableError
import time

BASE_DIR = 'scripts/kubernetes/resources'
SUCCESS_CODE = 201
WORKING_CODE = 200
ALREADY_EXISTS = 409


def get(path=None):

    url = 'http://{0}:8080/api/v1/namespaces'.format(ctx.instance.host_ip) \
        if not path else 'http://{0}:8080/api/v1/namespaces/{1}'.format(
        ctx.instance.host_ip, path
    )
    return requests.get(url)


def post(path=None, data=None):

    url = 'http://{0}:8080/api/v1/namespaces'.format(ctx.instance.host_ip) \
        if not path else 'http://{0}:8080/api/v1/namespaces/{1}'.format(
        ctx.instance.host_ip, path
    )

    return requests.post(url, data=json.dumps(data))


def create(api_object, data):

    if api_object == 'namespaces':
        response = post(path=None, data=data)
    else:
        response = post(path='{0}/{1}'.format(
            ctx.instance.runtime_properties['namespace'],
            api_object),
            data=data
        )

    ctx.logger.debug('response.text: {0}'.format(response.text))

    return response.status_code


def create_namespace(namespace):
    ctx.instance.runtime_properties['namespace'] = namespace

    nsp_file = ctx.download_resource(os.path.join(BASE_DIR, 'namespace.yaml'))

    response = get(namespace)

    if response.status_code != WORKING_CODE:
        ctx.logger.debug('CODE: {0} RESP: {1}'.format(response.status_code, response.json()))
        with open(nsp_file, 'r') as f:
            nsp_yaml = yaml.load(f)
        created = create('namespaces', nsp_yaml)
        if created != SUCCESS_CODE and created != ALREADY_EXISTS:
            raise NonRecoverableError('Failed to create namespace.')

    timeout = time.time() + 30
    while True:
        namespace = get(namespace)
        if namespace.status_code == WORKING_CODE:
            ctx.logger.info('Namespace is setup.')
            ctx.logger.debug('namespace get response.text: {0}'.format(namespace.text))
            break
        if time.time() > timeout:
            ctx.logger.debug('namespace get response.text: {0}'.format(namespace.text))
            raise NonRecoverableError('Timed out waiting for namespace.')

    timeout = time.time() + 30
    while True:
        serviceaccounts = get('{0}/serviceaccounts'.format(namespace))
        if serviceaccounts.status_code == WORKING_CODE:
            ctx.logger.info('Namespace Service Account is setup.')
            ctx.logger.debug('serviceaccounts get response.text: {0}'.format(serviceaccounts.text))
            break
        if time.time() > timeout:
            ctx.logger.debug('serviceaccounts get response.text: {0}'.format(serviceaccounts.text))
            raise NonRecoverableError('Timed out waiting for Service Account.')


if __name__ == '__main__':

    ctx.logger.info('Installing Kubernetes Dashboard')

    pip.main(['install', 'PyYAML==3.10'])
    namespace = inputs['namespace']
    import yaml
    create_namespace(namespace)
