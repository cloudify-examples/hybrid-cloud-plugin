#!/usr/bin/env python

import os
import time
import subprocess
from cloudify import ctx
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError, RecoverableError

os.environ['MASTER_IP'] = inputs['the_master_ip_here']
work_environment = os.environ.copy()
work_dir = os.path.expanduser("~")

FLANNEL_PULL_COMMAND = 'docker -H unix:///var/run/docker-bootstrap.sock pull quay.io/coreos/flannel:${FLANNEL_VERSION}'
FLANNEL_RUN_COMMAND = 'docker -H unix:///var/run/docker-bootstrap.sock run -d --net=host --privileged -v /dev/net:/dev/net quay.io/coreos/flannel:${FLANNEL_VERSION} /opt/bin/flanneld --ip-masq=${FLANNEL_IPMASQ} --etcd-endpoints=http://${MASTER_IP}:4001 --iface=${FLANNEL_IFACE}'
FLANNEL_SUBNET_ENV = 'docker -H unix:///var/run/docker-bootstrap.sock exec {0} cat /run/flannel/subnet.env'

CMD_APP = 'DOCKER_OPTS="--bip=${FLANNEL_SUBNET} --mtu=${FLANNEL_MTU}"'
SUCCESS_PROCESS = 'pgrep -f \'docker-containerd-shim {0}\''

STOP_DOCKER_CONTAINER = 'docker stop {0}'
REMOVE_DOCKER_CONTAINER = 'docker rm {0}'


def run_flannel():

    ctx.logger.info('ENV: {0}'.format(work_environment))

    subprocess.Popen(
        FLANNEL_PULL_COMMAND,
        stdout=open('/tmp/flannel-out.log', 'w'),
        stderr=open('/tmp/flannel-err.log', 'w'),
        env=work_environment,
        shell=True
    ).wait()

    result = subprocess.Popen(
        FLANNEL_RUN_COMMAND,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    output, error = result.communicate()

    ctx.logger.debug(
        'Output: {0}' \
        'Error: {1}'.format(output, error)
    )

    if result.returncode:
        raise NonRecoverableError('Failed to start Flannel.')

    container_id = output.strip()

    ctx.instance.runtime_properties['container_id'] = container_id

    command = SUCCESS_PROCESS.format(container_id)
    timeout = time.time() + 60
    while True:
        success_process = subprocess.Popen(
            command.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if not success_process.returncode:
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for Docker bootstrap to start.'
            )

    container_id = ctx.instance.runtime_properties['container_id']

    command = FLANNEL_SUBNET_ENV.format(container_id)

    ctx.logger.debug('Command: {0}'.format(command))

    result = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    output, error = result.communicate()

    if result.returncode:
        if ctx.operation.retry_number < 5:
            command = STOP_DOCKER_CONTAINER.format(container_id)
            subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=work_environment,
                shell=True
            ).wait()
            command = REMOVE_DOCKER_CONTAINER.format(container_id)
            subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=work_environment,
                shell=True
            ).wait()
            return ctx.operation.retry(
                'Failed to get Flannel subnet env for '
                'container_id: {0}'.format(container_id)
            )
        raise NonRecoverableError(
            'Failed to get Flannel subnet env. '
            'Output: {0}' \
            'Error: {1}'.format(output, error)
        )

    flannel_output = output

    ctx.logger.info('output: {0}'.format(flannel_output))

    flannel = ';'.join(flannel_output.split('\n'))

    ctx.logger.info('flannel: {0}'.format(flannel))

    return flannel


def edit_docker_config(flannel):

    if not flannel:
        return ctx.operation.retry(
            'Flannel is empty {0}'.format(flannel)
        )

    with open('/tmp/docker', 'w') as fd:
        with open('/etc/default/docker', 'r') as fdin:
            for line in fdin:
                fd.write(line)

    with open('/tmp/docker', 'a') as fd:
        fd.write('{0}\n'
                 '{1}\n'.format(flannel, CMD_APP)
                 )

    try:
        subprocess.call('sudo mv /tmp/docker /etc/default/docker', shell=True)
    except:
        raise NonRecoverableError('Unable to move Docker config into place.')


if __name__ == '__main__':

    ctx.logger.info('Starting Flannel on Node')

    if ctx.operation.retry_number < 1:

        command = 'sudo service docker stop'

        result = subprocess.Popen(
            command.split(),
            stdout=open(os.devnull, 'w'),
            stderr=subprocess.PIPE
        )

        output, error = result.communicate()

        if result.returncode:
            raise NonRecoverableError(
                'Failed to stop Docker. '
                'Output: {0}' \
                'Error: {1}'.format(output, error)
            )

    ctx.instance.runtime_properties['flannel'] = run_flannel()

    flannel_args = ctx.instance.runtime_properties['flannel']

    edit_docker_config(flannel_args)
