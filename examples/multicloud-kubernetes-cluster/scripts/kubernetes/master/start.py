#!/usr/bin/env python

import subprocess
import os
import time
from cloudify import ctx
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError

os.environ['MASTER_IP'] = inputs['the_master_ip_here']
work_environment = os.environ.copy()
work_dir = os.path.expanduser("~")

HYPERKUBE_PULL_COMMAND = 'docker pull gcr.io/google_containers/hyperkube-amd64:v${K8S_VERSION}'
START_HYPERKUBE = 'docker run --volume=/:/rootfs:ro --volume=/sys:/sys:ro --volume=/var/lib/docker/:/var/lib/docker:rw --volume=/var/lib/kubelet/:/var/lib/kubelet:rw --volume=/var/run:/var/run:rw --net=host --privileged=true --pid=host -d gcr.io/google_containers/hyperkube-amd64:v${K8S_VERSION} /hyperkube kubelet --allow-privileged=true --api-servers=http://localhost:8080 --v=2 --address=0.0.0.0 --enable-server --hostname-override=127.0.0.1 --config=/etc/kubernetes/manifests-multi --containerized --cluster-dns=18.1.0.1 --cluster-domain=cluster.local'


def start_master():

    subprocess.Popen(
        HYPERKUBE_PULL_COMMAND,
        stdout=open('/tmp/hyperkube-out.log', 'w'),
        stderr=open('/tmp/hyperkube-err.log', 'w'),
        env=work_environment,
        shell=True
    ).wait()

    process = subprocess.Popen(
        START_HYPERKUBE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    output, error = process.communicate()

    if process.returncode:
        if 'Unable to find image' in error:
            return ctx.operation.retry(
                'Retry start: Output: {0} '
                'Error: {1}'.format(output, error)
            )
        raise NonRecoverableError(
            'Failed to start Kubernetes master. '
            'Output: {0}' \
            'Error: {1}'.format(output, error)
        )

    return


def remove_docker_bridge():

    list_of_commands = [
        'sudo /sbin/ifconfig docker0 down',
        'sudo apt-get install -y bridge-utils',
        'sudo brctl delbr docker0',
        'sudo ifconfig'
    ]

    for command in list_of_commands:
        result = subprocess.Popen(
            command.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=work_environment
        )
        output, error = result.communicate()
        ctx.logger.debug(
            'Command: {0} '
            'Command output: {1} '
            'Command error: {2}'.format(command, output, error))
        if result.returncode:
            raise NonRecoverableError(
                'Error: {0}'
                'Output: {1}'.format(error, output)
            )


if __name__ == '__main__':

    ctx.logger.info('Starting Kubernetes Master')

    if ctx.operation.retry_number < 1:

        remove_docker_bridge()

    if ctx.operation.retry_number < 1:

        command = 'sudo service docker start'

        result = subprocess.Popen(
            command.split(),
            stdout=open(os.devnull, 'w'),
            stderr=subprocess.PIPE
        )

        output, error = result.communicate()

        if result.returncode:
            raise NonRecoverableError(
                'Failed to start Docker '
                'Error: {0}' \
                'Output: {1}'.format(error, output)
            )

    start_master()
