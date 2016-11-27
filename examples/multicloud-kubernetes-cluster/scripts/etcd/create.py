#!/usr/bin/env python

from cloudify import ctx
import os
import subprocess
import time
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError

os.environ['MASTER_IP'] = inputs['the_master_ip_here']
work_environment = os.environ.copy()

ETCD_BOOTSTRAP_COMMAND = 'sudo docker -H unix:///var/run/docker-bootstrap.sock run -d --net=host gcr.io/google_containers/etcd-amd64:${ETCD_VERSION} /usr/local/bin/etcd --listen-client-urls=http://127.0.0.1:4001,http://${MASTER_IP}:4001 --advertise-client-urls=http://${MASTER_IP}:4001 --data-dir=/var/etcd/data'
ETCD_CIDR_SETUP_COMMAND = 'sudo docker -H unix:///var/run/docker-bootstrap.sock exec {0} etcdctl set /coreos.com/network/config \'{{ "Network": "18.1.0.0/16" }}\''
ETCD_PROCESS = 'pgrep -f \'/usr/local/bin/etcd\''
ETCD_CIDR_VERIFY_COMMAND = 'sudo docker -H unix:///var/run/docker-bootstrap.sock exec {0} etcdctl get /coreos.com/network/config'


def start_etcd():

    ctx.logger.debug('Running the etcd container.')

    try:
        etc_file = ctx.download_resource(
            'scripts/etcd/resources/etcd.tar')
        ETCD_PULL = \
            'sudo docker -H ' \
            'unix:///var/run/docker-bootstrap.sock load -i {0}' \
            .format(etc_file)
    except RuntimeError:
        ETCD_PULL = \
            'sudo docker pull ${ETCD_VERSION}'

    subprocess.Popen(
        ETCD_PULL,
        env=work_environment,
        stdout=open('/tmp/etcd-out.log', 'w'),
        stderr=open('/tmp/etcd-err.log', 'w'),
        shell=True
    ).wait()

    process = subprocess.Popen(
        ETCD_BOOTSTRAP_COMMAND,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    output, error = process.communicate()

    if process.returncode:
        raise NonRecoverableError(
            'Failed to start etcd. '
            'Output: {0}' \
            'Error: {1}'.format(output, error)
        )

    return output


def setup_cidr_range_for_flannel(container_id):

    ctx.logger.debug('setup_cidr_range_for_flannel')
    command = ETCD_CIDR_SETUP_COMMAND.format(container_id)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    )

    if process.returncode:
        output, error = process.communicate()
        raise NonRecoverableError(
            'Failed to setup CIDR for Flannel. '
            'Command: {0} '
            'Output: {1} '
            'Error: {2}'.format(command, output, error)
        )

    return


def verify(container_id):

    ctx.logger.debug('Verifying that etcd is ready for flannel')

    command = ETCD_CIDR_VERIFY_COMMAND.format(container_id)

    for counter in range(0,5):

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=work_environment,
            shell=True
        )

        output, error = process.communicate()
        ctx.logger.debug(
            'Command: {0} '
            'Command output: {1} '
            'Command error: {2}'.format(command, output, error)
        )

        if "Network" in output:
            ctx.logger.debug('ETCD configured.')
            return
        elif counter == 4 and ctx.operation.retry_number > 4:
            raise NonRecoverableError(
                'Failed to setup CIDR for Flannel. '
                'Command: {0} '
                'Output: {1} '
                'Error: {2}'.format(command, output, error)
            )

    stop_container = 'sudo docker stop {0}'.format(container_id)
    subprocess.Popen(
        stop_container,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=work_environment,
        shell=True
    ).wait()
    return ctx.operation.retry(
        'Failed to setup CIDR for Flannel. '
        'Command: {0} '
        'Output: {1} '
        'Error: {2}'.format(command, output, error)
    )


if __name__ == '__main__':

    ctx.logger.info('initializing etcd')
    ctx.logger.info('{0}'.format(os.environ.keys()))
    output = start_etcd()
    ctx.logger.debug('output: {0}'.format(output))
    container_id = output.strip()
    time.sleep(2)
    timeout = time.time() + 5
    while True:
        success_process = subprocess.Popen(
            ETCD_PROCESS.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if not success_process.returncode:
            break
        if time.time() > timeout:
            raise NonRecoverableError(
                'Timed out waiting for etcd container to start.'
            )
    setup_cidr_range_for_flannel(container_id)
    verify(container_id)
