import pip
import os
import requests
import json
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError

BASE_DIR = 'scripts/kubernetes/resources/nginx'
SUCCESS_CODE = 201
WORKING_CODE = 200
DUPLICATE_CODE = 409
IP_ALREADY_ALLOCATED = 422

def check_existing(api_object, data):

    name = data.get('metadata').get('name')

    response = requests.get(
        'http://{0}:8080/api/v1/namespaces/default/{1}/{2}'.format(
            ctx.instance.host_ip,
            api_object, name)
    )

    return False if response.status_code != WORKING_CODE else True


def create(api_object, data):

    if check_existing(api_object, data):
        return ctx.operation.retry('Something already exists. Check debug log.')

    response = requests.post(
        'http://{0}:8080/api/v1/namespaces/default/{1}'.format(
            ctx.instance.host_ip,
            api_object),
        data=json.dumps(data)
    )

    ctx.logger.debug('Response JSON: {0}'.format(response.json()))

    if 'services' in api_object and SUCCESS_CODE == response.status_code:
        ctx.instance.runtime_properties['ip'] = response.json().get('spec').get('clusterIP')
        ctx.instance.runtime_properties['port'] = response.json().get('spec').get('ports')[0].get('port')

    return response.status_code


def create_app():

    pod_file = ctx.download_resource(os.path.join(BASE_DIR, 'pod.yaml'))
    rc_file = ctx.download_resource(os.path.join(BASE_DIR, 'rc.yaml'))
    svc_file = ctx.download_resource(os.path.join(BASE_DIR, 'svc.yaml'))

    with open(pod_file, 'r') as f:
        pod_yaml = yaml.load(f)

    create_pod_output = create('pods', pod_yaml)

    if create_pod_output != SUCCESS_CODE:
        raise NonRecoverableError('Failed to create pod.')

    with open(rc_file, 'r') as f:
        rc_yaml = yaml.load(f)

    create_rc_output = create('replicationcontrollers', rc_yaml)

    if create_rc_output != SUCCESS_CODE:
        raise NonRecoverableError('Failed to create replication controller.')

    with open(svc_file, 'r') as f:
        svc_yaml = yaml.load(f)

    create_service_output = create('services', svc_yaml)

    if create_service_output != SUCCESS_CODE:
        raise NonRecoverableError('Failed to create service.')


if __name__ == '__main__':

    ctx.logger.info('Testing Kubernetes')

    pip.main(['install', 'PyYAML==3.10'])
    import yaml
    create_app()
