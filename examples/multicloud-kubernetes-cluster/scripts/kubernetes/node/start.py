#!/usr/bin/env python

from cloudify import ctx
import subprocess
import socket
import fcntl
import struct
import os
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError

os.environ['MASTER_IP'] = inputs['the_master_ip_here']
work_environment = os.environ.copy()
work_dir = os.path.expanduser("~")

HYPERKUBE_PULL_COMMAND = 'docker pull gcr.io/google_containers/hyperkube-amd64:v${K8S_VERSION}'
START_HYPERKUBE = 'docker run --volume=/:/rootfs:ro --volume=/sys:/sys:ro --volume=/dev:/dev --volume=/var/lib/docker/:/var/lib/docker:rw --volume=/var/lib/kubelet/:/var/lib/kubelet:rw --volume=/var/run:/var/run:rw --net=host --privileged=true --pid=host -d gcr.io/google_containers/hyperkube-amd64:v${K8S_VERSION} /hyperkube kubelet --allow-privileged=true --api-servers=http://${MASTER_IP}:8080 --v=2 --address=0.0.0.0 --enable-server --containerized --hostname-override=${LOCAL_IP} --cluster-dns=18.1.0.1 --cluster-domain=cluster.local'
START_PROXY = 'docker run -d --net=host --privileged gcr.io/google_containers/hyperkube-amd64:v${K8S_VERSION} /hyperkube proxy --master=http://${MASTER_IP}:8080 --v=2'


def get_ip_address(ifname):

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    ip_address = socket.inet_ntoa(
        fcntl.ioctl(
            s.fileno(), 0x8915,
            struct.pack('256s', ifname[:15])
        )[20:24]
    )

    return ip_address


def remove_docker_bridge():

    list_of_commands = [
        'sudo /sbin/ifconfig docker0 down',
        'sudo apt-get install -y bridge-utils',
        'sudo brctl delbr docker0'
    ]

    for command in list_of_commands:
        result = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=work_environment,
            shell=True
        )
        output = result.communicate()
        if result.returncode:
            raise NonRecoverableError(
                'Error: {0}' \
                'Output: {1}'.format(result.returncode, output)
            )

    return


def start_node():

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


def start_proxy():

    process = subprocess.Popen(
        START_PROXY,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    output, error = process.communicate()

    if process.returncode:
        raise NonRecoverableError(
            'Failed to start Kubernetes master. '
            'Output: {0}' \
            'Error: {1}'.format(output, error)
        )

    return


if __name__ == '__main__':

    ctx.logger.info('Starting Kubernetes Node')

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

    interface = str(os.environ['FLANNEL_IFACE'])
    work_environment.update({'LOCAL_IP': get_ip_address(interface)})

    start_node()
    start_proxy()
