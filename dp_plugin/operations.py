######
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

from cloudify.decorators import operation
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError, RecoverableError
from cloudify.workflows.local import StorageConflictError
from cloudify_rest_client.exceptions import CloudifyClientError

PLANS = 'deployment_plans'
BA = 'burst_after'
MANAGED_BY = 'managed_by'
MANAGING = 'managing'


def get_endpoint():
    if hasattr(ctx._endpoint, 'storage'):
        return ctx._endpoint.storage
    return ctx._endpoint

def get_node(id):
    endpoint = get_endpoint()
    return endpoint.get_node_instance(id)

def get_node_instance(id):
    endpoint = get_endpoint()
    return endpoint.get_node_instance(id)

def update_node_instance(node_instance):
    endpoint = get_endpoint()
    return endpoint.update_node_instance(node_instance)

def get_burst_plan(plans):
    burst_after = ''
    for plan_name, plan in plans.items():
        if ctx.target.node.name in plan_name:
            burst_after = plan.get(BA)
    return burst_after

def get_agent_config(ctx_node_properties):
    agent_config = ctx_node_properties.get('agent_config')
    if 'none' not in agent_config['install_method']:
        raise NonRecoverableError(
            'The agent_config install_method must '
            'be none on the target of '
            'cloudify.dp.relationships.plans')
    agent_config['install_method'] = 'remote'
    return agent_config


@operation
def create(args, **_):

    target_node_instance = None

    for target_id, target_props in ctx.capabilities._capabilities.items():
        target_node_instance = get_node_instance(target_id)
        if not target_node_instance.runtime_properties.get(MANAGED_BY):
            try:
                ctx.instance.runtime_properties[MANAGING] = target_id
                target_node_instance.runtime_properties[MANAGED_BY] = ctx.instance.id
                update_node_instance(target_node_instance)
            except:
                ctx.logger.info('did not succeed')
                return ctx.operation.retry('TRying again')
            break

    if not target_node_instance:
        raise NonRecoverableError('Nothing to create')
    ctx.logger.info('{0} paired with {1}'.format(ctx.instance.id, target_node_instance.id))


@operation
def preconfigure_plan(args, **_):

    source_managing = ctx.source.instance.runtime_properties.get(MANAGING)
    source_id = ctx.source.instance.id
    target_managed_by = ctx.target.instance.runtime_properties.get(MANAGED_BY)
    target_id = ctx.target.instance.id

    if source_managing == target_id and target_managed_by == source_id:
        burst_after = get_burst_plan(ctx.source.node.properties[PLANS])
        agent_config = get_agent_config(ctx.target.node.properties)
        target_id = ctx.target.instance.id
        target_ip = ctx.target.instance.host_ip
        dp_instance = {
            'id': target_id,
            'ip': target_ip,
            'available': True,
            'agent_config': agent_config,
            BA: burst_after
        }
        dp_instance.update(args)
        try:
            ctx.source.instance.runtime_properties[target_id] = dp_instance
            ctx.source.instance.runtime_properties['ip'] = target_ip
            ctx.source.instance.runtime_properties['cloudify_agent'] = agent_config
        except CloudifyClientError as e:
            del ctx.target.instance.runtime_properties[target_id]
            del ctx.target.instance.runtime_properties['ip']
            del ctx.target.instance.runtime_properties['cloudify_agent']
            return ctx.operation.retry('Unable to Pair.')

@operation
def unlink_plan(args, **_):
    del ctx.source.instance.runtime_properties[ctx.target.instance.id]
    del ctx.target.instance.runtime_properties[MANAGED_BY]

@operation
def delete(args, **_):
    ctx.instance.runtime_properties.pop('ip')
    ctx.instance.runtime_properties.pop('cloudify_agent')
