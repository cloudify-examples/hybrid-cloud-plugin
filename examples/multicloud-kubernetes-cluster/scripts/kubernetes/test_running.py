import requests
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
import time
from requests.exceptions import ConnectTimeout

BASE_DIR = 'scripts/kubernetes/resources/nginx'
SUCCESS_CODE = 201
WORKING_CODE = 200


def check_app():

    response = requests.get(
        'http://{0}:8080/api/v1/namespaces/default/services/nginx-service'.format(
            ctx.instance.host_ip)
    )

    if response.status_code != WORKING_CODE:
        raise NonRecoverableError('Application creation failed completely.')

    timeout = time.time() + 5
    while True:
        try:
            response = requests.get('http://{0}:{1}'.format(
                ctx.instance.runtime_properties['ip'],
                ctx.instance.runtime_properties['port']),
                timeout=0.5
            )
        except ConnectTimeout:
            time.sleep(.5)
        if response.status_code != WORKING_CODE:
            time.sleep(1)
            continue
        elif response.status_code == WORKING_CODE:
            ctx.logger.info('Application started and worked.')
            break
        elif time.time() > timeout:
            return ctx.operation.retry('Application did not start yet.')


def teardown_app():
    response = requests.delete(
        'http://{0}:8080/api/v1/namespaces/default/services/nginx-service'.format(
            ctx.instance.host_ip
        )
    )
    ctx.logger.debug('Response: {0}'.format(response.json()))
    response = requests.delete(
        'http://{0}:8080/api/v1/namespaces/default/replicationcontrollers/nginx-controller'.format(
            ctx.instance.host_ip
        )
    )
    ctx.logger.debug('Response: {0}'.format(response.json()))
    response = requests.delete(
        'http://{0}:8080/api/v1/namespaces/default/pods/nginx'.format(
            ctx.instance.host_ip
        )
    )
    ctx.logger.debug('Response: {0}'.format(response.json()))

    def final_cleanup():
        # For some reason there are remaining nginx rcs.
        # TODO: Fix
        response = requests.get(
            'http://{0}:8080/api/v1/namespaces/default/pods/'.format(
                ctx.instance.host_ip
            )
        )
        for item in response.json().get('items'):
            name = item.get('metadata').get('name')
            if 'nginx-controller' in name:
                requests.delete(
                    'http://{0}:8080/api/v1/namespaces/default/pods/{1}'.format(
                        ctx.instance.host_ip,
                        name
                    )
                )
    final_cleanup()


if __name__ == '__main__':

    ctx.logger.info('Testing Kubernetes')

    if ctx.operation.retry_number > 15:
        raise NonRecoverableError('Application never successfully started after 15 checks.')

    check_app()

    teardown_app()
