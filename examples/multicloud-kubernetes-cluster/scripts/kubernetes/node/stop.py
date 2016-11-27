#!/usr/bin/env python

import requests
from cloudify import ctx
from cloudify.state import ctx_parameters as inputs


def verify_master_ready(ip, host):
    nodes = requests.delete('http://{0}:8080/api/v1/nodes/{1}'.format(ip, host))
    ctx.logger.debug('NODES: {0}'.format(nodes.text))


if __name__ == '__main__':
    ctx.logger.info('Removing the Kubernetes Node from rotation')
    master_ip = inputs['master_ip']
    hostname = ctx.instance.host_ip
    verify_master_ready(master_ip, hostname)
