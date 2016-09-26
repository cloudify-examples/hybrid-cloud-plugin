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

from cloudify.decorators import workflow
from cloudify.plugins import lifecycle
from cloudify.exceptions import NonRecoverableError

PLAN_RS = 'cloudify.dp.relationships.plans'
PLANS = 'deployment_plans' 
BA = 'burst_after'
MANAGING = 'managing'


def generic_scale(modification, graph):

    try:
        ctx.logger.info('Deployment modification started. '
                        '[modification_id={0}]'.format(modification.id))
        if delta > 0:
            added_and_related = set(modification.added.node_instances)
            added = set(i for i in added_and_related
                        if i.modification == 'added')
            related = added_and_related - added
            try:
                lifecycle.install_node_instances(
                    graph=graph,
                    node_instances=added,
                    related_nodes=related)
            except:
                ctx.logger.error('Scale out failed, scaling back in.')
                for task in graph.tasks_iter():
                    graph.remove_task(task)
                lifecycle.uninstall_node_instances(
                    graph=graph,
                    node_instances=added,
                    related_nodes=related)
                raise
        else:
            removed_and_related = set(modification.removed.node_instances)
            removed = set(i for i in removed_and_related
                          if i.modification == 'removed')
            related = removed_and_related - removed
            lifecycle.uninstall_node_instances(
                graph=graph,
                node_instances=removed,
                related_nodes=related)
    except:
        ctx.logger.warn('Rolling back deployment modification. '
                        '[modification_id={0}]'.format(modification.id))
        try:
            modification.rollback()
        except:
            ctx.logger.warn('Deployment modification rollback failed. The '
                            'deployment model is most likely in some corrupted'
                            ' state.'
                            '[modification_id={0}]'.format(modification.id))
            raise
        raise
    else:
        try:
            modification.finish()
        except:
            ctx.logger.warn('Deployment modification finish failed. The '
                            'deployment model is most likely in some corrupted'
                            ' state.'
                            '[modification_id={0}]'.format(modification.id))
            raise


@workflow
def scale_or_burst(ctx, scalable_entity_name, delta, **_):

    """
    scalable_entity_name: Must be a deployment plan node type
    delta: total new number of instances
    """

    delta = int(delta)

    dp_node = ctx.get_node(scalable_entity_name)

    if not dp_node:
        raise ValueError("Node {0} doesn't exist".format(scalable_entity_name))
    if delta == 0:
        ctx.logger.info('delta parameter is 0, so no scaling will take place.')
        return

    dp_node_plans = dp_node.properties.get(PLANS)
    ctx.logger.debug('{0}'.format(dp_node.relationships))
    dp_node_group_ids = [rs.target_id if PLAN_RS in rs._relationship["type_hierarchy"] else None for rs in dp_node.relationships]
    dp_nodes_group = {}

    modification_data = {
        dp_node.id: { 'instances': dp_node.number_of_instances + delta }
    }

    def temporarily_lock_node(node_id):
            node_to_lock = dp_nodes_group[node_id]
            if not node_to_lock.get('locked'):
                node_to_lock['locked'] = 1
            elif node_to_lock['locked'] == len(dp_nodes_group):
                node_to_lock['locked'] = 0
            elif node_to_lock['locked']:
                node_to_lock['locked'] += 1

    def update_deployment_modification(number_of_instances_to_add, node_id_to_update):
        node_to_update = ctx.get_node(node_id_to_update)
        modification_data.update({node_to_update.id: {'instances': node_to_update.number_of_instances + number_of_instances_to_add }})
        ctx.logger.debug('New modification_data: {0}'.format(modification_data))

    def assign_delta_to_nodes(node_id):
        unassigned_delta_in_fn = 0
        assigned_node_in_fn = 0
        node = dp_nodes_group.get(node_id)
        ctx.logger.debug('Assigning: {0}'.format(node))
        for constraint_id, constraint_threshold in node.get('constraints', {}).items():
            if dp_nodes_group[constraint_id].get('count') < constraint_threshold:
                assigned_node_in_fn = assign_delta_to_nodes(constraint_id)
                dp_nodes_group[constraint_id]['count'] += assigned_node_in_fn
                update_deployment_modification(assigned_node_in_fn, constraint_id)
                unassigned_delta_in_fn += assigned_node_in_fn
            elif not node.get('locked'):
                assigned_node_in_fn = assign_delta_to_nodes(constraint_id)
                dp_nodes_group[constraint_id]['count'] += assigned_node_in_fn
                update_deployment_modification(assigned_node_in_fn, constraint_id)
                unassigned_delta_in_fn += assigned_node_in_fn
        if node.get('capacity', float('inf')) > node.get('count'):
                update_deployment_modification(1, node_id)
                return 1 + assigned_node_in_fn
        return 0

    for dp_node_id in dp_node_group_ids:
        this_dp_node = ctx.get_node(dp_node_id)
        dp_nodes_group.update({
            dp_node_id: {
                'count': int(this_dp_node.number_of_instances),
                'capacity': dp_node_plans.get(dp_node_id, {}).get('capacity', {}),
                'constraints': dp_node_plans.get(dp_node_id, {}).get('constraints', {})
            }
        })

    unassigned_delta = delta
    assigned_delta = 0

    while unassigned_delta > 0:
        node_id_to_assign = dp_node_group_ids.pop()
        ctx.logger.debug('Assigning: {0}'.format(node_id_to_assign))
        assigned_node = assign_delta_to_nodes(node_id_to_assign)
        if assigned_node:
            temporarily_lock_node(node_id_to_assign)
            dp_node_group_ids.append(node_id_to_assign)
        assigned_delta += assigned_node
        unassigned_delta -= assigned_node

    ctx.logger.debug('modification_data: {0}'.format(modification_data))

    modification = ctx.deployment.start_modification(modification_data)
    graph = ctx.graph_mode()
    generic_scale(modification, graph)

@workflow
def heal_dp(
        ctx,
        node_instance_id,
        diagnose_value='Not provided',
        **kwargs):

    ctx.logger.info("Starting 'dp_heal' workflow on {0}, Diagnosis: {1}"
                    .format(node_instance_id, diagnose_value))
    failing_node = ctx.get_node_instance(node_instance_id)
    failing_node_host = ctx.get_node_instance(
        failing_node._node_instance.host_id
    )

    subgraph_node_instances = failing_node_host.get_contained_subgraph()
    failing_dp_node_managing_host_id = failing_node.runtime_properties[MANAGING]
    failing_dp_node_managing_host = ctx.get_node_instance(failing_dp_node_managing_host_id)
    subgraph_node_instances.update(failing_dp_node_managing_host.get_contained_subgraph())
    intact_nodes = set(ctx.node_instances) - subgraph_node_instances
    graph = ctx.graph_mode()
    lifecycle.reinstall_node_instances(
        graph=graph,
        node_instances=subgraph_node_instances,
        related_nodes=intact_nodes)
