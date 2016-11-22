#!/usr/bin/env python

import requests
from cloudify import ctx
from cloudify.state import ctx_parameters as inputs
from cloudify.exceptions import NonRecoverableError

max_retries = inputs['max_retries']


def verify_master_ready(ip, host):
    nodes = requests.get('http://{0}:8080/api/v1/nodes'.format(ip)).json()
    ctx.logger.debug('NODES: {0}'.format(nodes))
    for item in nodes.get('items'):
        if host in item.get('metadata').get('name'):
            for condition in item.get('status').get('conditions'):
                if 'Ready' in condition.get('type') and 'True' not in condition.get('status'):
                    return ctx.operation.retry('Kubelet not yet ready: {0}'.format(host))
                elif 'Ready' in condition.get('type') and 'True' in condition.get('status'):
                    ctx.logger.info('Kubelet ready: {0}'.format(host))



if __name__ == '__main__':

    if ctx.operation.retry_number > max_retries > 0:
        raise NonRecoverableError(
            'Failed to verify after {0} retries.'.format(
                ctx.operation.retry_number
            )
        )

    ctx.logger.info('Verifying Kubelet')
    master_ip = inputs['master_ip']
    hostname = inputs['hostname']
    if not hostname:
        hostname = ctx.source.instance.host_ip
    verify_master_ready(master_ip, hostname)
