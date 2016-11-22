import pip
import os
import requests
import json
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
import time

BASE_DIR = 'scripts/kubernetes/resources/dns'
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

    ctx.instance.runtime_properties['dns_domain'] = 'cluster.local'
    ctx.instance.runtime_properties['dns_replicas'] = 1
    ctx.instance.runtime_properties['enable_cluster_dns'] = True

    rc_file = ctx.download_resource_and_render(
        os.path.join(BASE_DIR, 'rc.yaml'))
    svc_file = ctx.download_resource_and_render(
        os.path.join(BASE_DIR, 'svc.yaml'))

    response = get('kube-system/replicationcontrollers/kube-dns-v11')

    if response.status_code != WORKING_CODE:
        ctx.logger.debug('CODE: {0} RESPONSE: {1}'.format(response.status_code, response.json()))
        with open(rc_file, 'r') as f:
            rc_yaml = yaml.load(f)
        created = create('replicationcontrollers', rc_yaml)
        if created != SUCCESS_CODE and created != ALREADY_EXISTS:
            raise NonRecoverableError('Failed to create replication controller.')

    timeout = time.time() + 60
    while True:
        response = get('kube-system/replicationcontrollers/kube-dns-v11')
        if response.status_code == WORKING_CODE:
            ctx.logger.info('DNS Replication Controller is working.')
            ctx.logger.debug('replicationcontroller get response.text: {0}'.format(response.text))
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for ReplicationController. '
                'More info: {0}'.format(response.text))

    response = get('kube-system/services/kube-dns')

    if response.status_code != WORKING_CODE:
        ctx.logger.debug('CODE: {0} RESP: {1}'.format(response.status_code, response.json()))
        with open(svc_file, 'r') as f:
            svc_yaml = yaml.load(f)
        created = create('services', svc_yaml)
        if created != SUCCESS_CODE and created != ALREADY_EXISTS:
            raise NonRecoverableError('Failed to create service.')
    timeout = time.time() + 30
    while True:
        response = get('kube-system/services/kube-dns')
        if response.status_code == WORKING_CODE:
            ctx.logger.info('DNS Service is working.')
            ctx.logger.debug('services get response.text: {0}'.format(response.text))
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for Service. '
                'More info: {0}'.format(response.text))


if __name__ == '__main__':

    ctx.logger.info('Installing Kubernetes DNS')
    ctx.instance.runtime_properties['dns_server_ip'] = '18.1.0.1'
    pip.main(['install', 'PyYAML==3.10'])
    import yaml
    create_app()
