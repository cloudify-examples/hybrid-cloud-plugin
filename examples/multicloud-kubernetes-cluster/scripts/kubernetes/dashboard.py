import pip
import os
import requests
import json
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
import time

BASE_DIR = 'scripts/kubernetes/resources/dashboard'
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
        response = post(path='kube-system/{0}'.format(api_object), data=data)

    ctx.logger.debug('response.text: {0}'.format(response.text))

    return response.status_code


def create_app():

    rc_file = ctx.download_resource(os.path.join(BASE_DIR, 'rc.yaml'))
    svc_file = ctx.download_resource(os.path.join(BASE_DIR, 'svc.yaml'))

    response = get('kube-system/replicationcontrollers/kubernetes-dashboard')

    if response.status_code != WORKING_CODE:
        ctx.logger.debug('CODE: {0} RESP: {1}'.format(response.status_code, response.json()))
        with open(rc_file, 'r') as f:
            rc_yaml = yaml.load(f)
        created = create('replicationcontrollers', rc_yaml)
        if created != SUCCESS_CODE and created != ALREADY_EXISTS:
            raise NonRecoverableError('Failed to create replication controller.')

    timeout = time.time() + 30
    while True:
        response = get('kube-system/replicationcontrollers/kubernetes-dashboard')
        if response.status_code == WORKING_CODE:
            ctx.logger.info('Kubernetes Dashboard Replication Controller is working.')
            ctx.logger.debug('replicationcontroller get response.text: {0}'.format(response.text))
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for ReplicationController. '
                'More info: {0}'.format(response.text))

    response = get('kube-system/services/kubernetes-dashboard')

    if response.status_code != WORKING_CODE:
        ctx.logger.debug('CODE: {0} RESP: {1}'.format(response.status_code, response.json()))
        with open(svc_file, 'r') as f:
            svc_yaml = yaml.load(f)
        created = create('services', svc_yaml)
        if created != SUCCESS_CODE and created != ALREADY_EXISTS:
            raise NonRecoverableError('Failed to create service.')
    timeout = time.time() + 30
    while True:
        response = get('kube-system/services/kubernetes-dashboard')
        if response.status_code == WORKING_CODE:
            ctx.logger.info('Kubernetes Dashboard Service is working.')
            ctx.logger.debug('services get response.text: {0}'.format(response.text))
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for Service. '
                'More info: {0}'.format(response.text))


if __name__ == '__main__':

    ctx.logger.info('Installing Kubernetes Dashboard')

    pip.main(['install', 'PyYAML==3.10'])
    import yaml

    create_app()
    time.sleep(5)

    counter = 0
    loop_max = 60
    for x in range(0,loop_max):

        response = requests.get(
            'http://{0}:8080/ui'.format(
                ctx.instance.host_ip)
        )

        if response.status_code == WORKING_CODE:
            ctx.logger.info('Dashboard ready.')
            break
        elif counter >= loop_max - 1:
            raise NonRecoverableError('Dashboard Never Started')

        counter = counter + 1
        time.sleep(1)

