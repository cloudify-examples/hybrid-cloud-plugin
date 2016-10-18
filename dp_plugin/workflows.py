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
from cloudify import ctx
from cloudify.manager import get_rest_client

PLAN_RS = 'cloudify.dp.relationships.plans'
PLANS = 'deployment_plans'
BA = 'burst_after'
MANAGING = 'managing'


def get_list_of_node_instances(_ctx, node):

    rest = get_rest_client()
    return rest.node_instances.list(deployment_id=_ctx.deployment.id,
                                    node_name=node.id)


def get_node_instance(node_instance_id):
    rest = get_rest_client()
    return rest.node_instances.get(node_instance_id=node_instance_id)


def generic_scale(_ctx, delta, modification, graph):

    try:
        _ctx.logger.info('Deployment modification started. '
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
                _ctx.logger.error('Scale out failed, scaling back in.')
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
        _ctx.logger.warn('Rolling back deployment modification. '
                         '[modification_id={0}]'.format(modification.id))
        try:
            modification.rollback()
        except:
            _ctx.logger.warn('Deployment modification rollback failed. The '
                             'deployment model is most likely in some corrupted'
                             ' state.'
                             '[modification_id={0}]'.format(modification.id))
            raise
        raise
    else:
        try:
            modification.finish()
        except:
            _ctx.logger.warn('Deployment modification finish failed. The '
                             'deployment model is most likely in some corrupted'
                             ' state.'
                             '[modification_id={0}]'.format(modification.id))
            raise


def build_dp_node_rule(_dp_node_id, _count, _dp_node_plan):
    return {
        _dp_node_id: {
            'count': int(_count),
            'capacity': _dp_node_plan.get('capacity', {}),
            'constraints': _dp_node_plan.get('constraints', {})
        }
    }


# def temporarily_lock_node(nodes_group, node_id):
#     for node_to_lock_id, node_to_lock in nodes_group.items():
#         if node_id == node_to_lock_id and not node_to_lock.get('locked'):
#             node_to_lock['locked'] = 1
#         elif node_to_lock.get('locked') == len(nodes_group) and node_to_lock_id == node_id:
#             node_to_lock['locked'] = len(nodes_group)
#         elif not node_to_lock.get('locked') or node_to_lock.get('locked') == len(nodes_group):
#             node_to_lock['locked'] = 0
#         else:
#             node_to_lock['locked'] += 1
#     return nodes_group


def get_list_of_dp_node_ids(_dp_node):
    # Build a list of PLAN_RS relationship types to consider scaling
    return [rs.target_id if PLAN_RS in rs._relationship["type_hierarchy"]
            else None for rs in _dp_node.relationships]


def get_most_recent_count(_ctx, _node_id, modification_data):
    # This is required because unit testing is pretty much impossible due to inability to run a deployment update.
    if not modification_data.get(_node_id):
        _node = _ctx.get_node(_node_id)
        return int(_node.number_of_instances)
    return modification_data.get(_node_id).get('instances')

def update_deployment_modification(_ctx, number_of_new_instances, node_to_update, modification_data):
    current_instance_count = get_most_recent_count(_ctx, node_to_update.id, modification_data)
    modification_data.update(
        {
            node_to_update.id: {
                'instances': current_instance_count + number_of_new_instances
            }
        }
    )
    _ctx.logger.debug('Updated modification_data: {0}'.format(modification_data))
    return modification_data


def assign_delta_to_nodes(_ctx, node_id, unassigned_delta, modification_data, nodes_group):
    assigned_node_in_fn = 0
    node = nodes_group.get(node_id)
    node_count = get_most_recent_count(_ctx, node_id, modification_data)
    if nodes_group.get(node_id).get('capacity', float('inf')) == node_count:
        return assigned_node_in_fn, modification_data, nodes_group
    for constraint_id, constraint_threshold in node.get('constraints', {}).items():
        constraint_node = _ctx.get_node(constraint_id)
        constraint_node_current = get_most_recent_count(_ctx, constraint_id, modification_data)
        if constraint_node_current < constraint_threshold:
            assigned_node_in_fn, modification_data, nodes_group = assign_delta_to_nodes(_ctx,
                                                                                        constraint_id,
                                                                                        unassigned_delta,
                                                                                        modification_data,
                                                                                        nodes_group)
            unassigned_delta = unassigned_delta - assigned_node_in_fn
            modification_data = update_deployment_modification(_ctx,
                                                               assigned_node_in_fn,
                                                               constraint_node,
                                                               modification_data)
    most_recent_count = get_most_recent_count(_ctx, node_id, modification_data)
    new_count = most_recent_count + assigned_node_in_fn
    if node.get('capacity', float('inf')) >= new_count:
        _node_to_modify = _ctx.get_node(node_id)
        modification_data = update_deployment_modification(_ctx,
                                                           1,
                                                           _node_to_modify,
                                                           modification_data)
        return 1 + assigned_node_in_fn, modification_data, nodes_group
    return assigned_node_in_fn, modification_data, nodes_group


def build_modification_data_profile(_ctx, dp_node, delta):

    modification_data = {
        dp_node.id: { 'instances': dp_node.number_of_instances + delta }
    }
    _ctx.logger.debug('Initial Modification Data: {0}'.format(modification_data))

    dp_node_group_ids = get_list_of_dp_node_ids(dp_node)
    _ctx.logger.debug('Scaling Node: {0}. Possible targets: {1}'
                      .format(dp_node.id, dp_node_group_ids))

    dp_node_plans = dp_node.properties.get(PLANS)
    _ctx.logger.debug('DP Node Plans: {0}'.format(dp_node_plans))

    dp_nodes_group = {}
    for dp_node_id in dp_node_group_ids:
        this_dp_node = _ctx.get_node(dp_node_id)
        new_dp_node_rule = build_dp_node_rule(dp_node_id,
                                              this_dp_node.number_of_instances,
                                              dp_node_plans.get(dp_node_id, {}))
        dp_nodes_group.update(new_dp_node_rule)
    _ctx.logger.debug('DP Node Rules: {0}'.format(dp_node_plans))

    unassigned_delta = delta
    while unassigned_delta > 0:
        node_id_to_assign = dp_node_group_ids.pop(0)
        assigned_count, modification_data, dp_nodes_group = \
            assign_delta_to_nodes(_ctx,
                                  node_id_to_assign,
                                  unassigned_delta,
                                  modification_data,
                                  dp_nodes_group)
        dp_node_group_ids.append(node_id_to_assign)
        unassigned_delta = unassigned_delta - assigned_count

    _ctx.logger.debug('New modification_data: {0}'.format(modification_data))
    return modification_data


@workflow
def scale_or_burst(ctx, scalable_entity_name, delta, **_):

    """
    scalable_entity_name: Must be a deployment plan node type
    delta: total new number of instances
    """

    delta = int(delta)

    # This is the Deployment Plan node that we will scale
    # It will scale on target of its PLAN_RS relationships
    dp_node = ctx.get_node(scalable_entity_name)
    if not dp_node:
        raise ValueError("Node {0} doesn't exist".format(scalable_entity_name))
    if delta == 0:
        ctx.logger.info('delta parameter is 0, so no scaling will take place.')
        return

    modification_data = build_modification_data_profile(ctx, dp_node, delta)
    modification = ctx.deployment.start_modification(modification_data)
    graph = ctx.graph_mode()
    generic_scale(ctx, delta, modification, graph)


@workflow
def heal_dp(
        ctx,
        node_instance_id,
        diagnose_value='Not provided',
        **kwargs):

    ctx.logger.info("Starting 'dp_heal' workflow on {0}, Diagnosis: {1}"
                    .format(node_instance_id, diagnose_value))
    failing_node_instance = get_node_instance(node_instance_id)
    failing_node_host = ctx.get_node_instance(
        failing_node_instance.host_id
    )

    subgraph_node_instances = failing_node_host.get_contained_subgraph()
    failing_dp_node_managing_host_id = failing_node_host.runtime_properties[MANAGING]
    failing_dp_node_managing_host = ctx.get_node_instance(failing_dp_node_managing_host_id)
    subgraph_node_instances.update(failing_dp_node_managing_host.get_contained_subgraph())
    intact_nodes = set(ctx.node_instances) - subgraph_node_instances
    graph = ctx.graph_mode()
    lifecycle.reinstall_node_instances(
        graph=graph,
        node_instances=subgraph_node_instances,
        related_nodes=intact_nodes)
