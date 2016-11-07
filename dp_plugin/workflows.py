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

from burst import burst
from scale import generic_scale

from cloudify.decorators import workflow
from cloudify.plugins import lifecycle
from cloudify.manager import get_rest_client

PLAN_RS = 'cloudify.dp.relationships.plans'
PLANS = 'deployment_plans'
BA = 'burst_after'
MANAGING = 'managing'


def get_node_instance(node_instance_id):
    client = get_rest_client()
    return client.node_instances.get(node_instance_id=node_instance_id)


def get_deployment(deployment_id):
    client = get_rest_client()
    return client.deployments.get(deployment_id=deployment_id)


@workflow
def scale_or_burst(ctx, scalable_entity_name, delta, **_):
    delta = int(delta)
    modification_data = burst(ctx, scalable_entity_name, delta)

    deployment = get_deployment(ctx.deployment.id)
    nodes_to_scale = modification_data.keys()
    nodes_to_scale.remove(scalable_entity_name)
    for node_to_scale in nodes_to_scale:
        for group in deployment.get('groups'):
            members = deployment['groups'][group]['members']
            if node_to_scale in members:
                modification_data[group] = \
                    modification_data.pop(node_to_scale)
    ctx.logger.debug('Final new modification: {0}'.format(modification_data))
    modification = ctx.deployment.start_modification(modification_data)
    graph = ctx.graph_mode()
    generic_scale(ctx, delta, modification, graph)


@workflow
def heal_dp(ctx,
            node_instance_id,
            diagnose_value='Not provided',
            **kwargs):

    ctx.logger.info("Starting 'dp_heal' workflow on {0}, Diagnosis: {1}"
                    .format(node_instance_id, diagnose_value))

    # Get the mixed iaas node
    failing_node = ctx.get_node_instance(node_instance_id)
    failing_node_host = ctx.get_node_instance(
        failing_node._node_instance.host_id
    )

    # Get the target node of the mixed iaas node
    failing_mixed_host_node = get_node_instance(node_instance_id)
    failing_target_host_node_id = \
        failing_mixed_host_node.runtime_properties[MANAGING]

    failing_target_host_node = ctx.get_node_instance(
        failing_target_host_node_id)

    subgraph_node_instances = failing_target_host_node.get_contained_subgraph()
    subgraph_node_instances.update(failing_node_host.get_contained_subgraph())
    intact_nodes = set(ctx.node_instances) - subgraph_node_instances
    graph = ctx.graph_mode()
    lifecycle.reinstall_node_instances(
        graph=graph,
        node_instances=subgraph_node_instances,
        related_nodes=intact_nodes)
