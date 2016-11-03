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

from cloudify.manager import get_rest_client

TARGETS_RS = 'cloudify.dp.relationships.plans'
INSTANCES = 'instances'


def get_mixed_node_target_ids(_mixed_node):
    # Build a list of TARGETS_RS relationship types to consider scaling
    return [rs.target_id if TARGETS_RS in rs._relationship["type_hierarchy"]
            else None for rs in _mixed_node.relationships]


def lock_or_unlock_node(_instances_of_node):
    _new_instances_of_node = []
    for ni in _instances_of_node:
        node_instance_lock = \
            ni.runtime_properties.get('locked', 0)
        if node_instance_lock >= len(_instances_of_node):
            ni.runtime_properties['locked'] = 0  # unlocked
        else:
            ni.runtime_properties['locked'] = \
                node_instance_lock + 1  # locked
            _new_instances_of_node.append(ni)
    return _new_instances_of_node


def check_if_node_is_locked(_instances_of_node):
    locked_nodes = []
    for _ni in _instances_of_node:
        if _ni.runtime_properties.get('locked'):
            locked_nodes.append(_ni.id)
    return True if len(locked_nodes) > 0 else False


def get_latest_node_instance_count(_ctx, _node_id, _modification_data):
    if _modification_data.get(_node_id, None):
        return _modification_data[_node_id].get(INSTANCES, 0)
    node = _ctx.get_node(_node_id)
    return node.number_of_instances


def check_target_is_constrained(_ctx, _target_node_constraints):
    if _target_node_constraints:
        for constraining_node_id, constraint in _target_node_constraints:
            plan_node = _ctx.get_node(constraining_node_id)
            if constraint > plan_node.number_of_instances:
                return True
    return False


def burst_up(ctx, scalable_entity_name, delta):

    """
    scalable_entity_name: Must be a deployment plan node type
    delta: total new number of instances
    """

    client = get_rest_client()
    delta = int(delta)
    delta_copy = delta

    # This is the Mixed IaaS node that we will scale
    # It will scale on target of its PLAN_RS relationships
    mixed_node = ctx.get_node(scalable_entity_name)
    if not mixed_node:
        raise ValueError("Node {0} doesn't exist".format(scalable_entity_name))

    # Create the first part of the modification_data dictionary
    modification_data = {
        mixed_node.id: {INSTANCES: mixed_node.number_of_instances}
    }
    ctx.logger.debug(
        'Initial Modification Data: {0}'.format(modification_data))

    # Get a list of possible targets
    mixed_target_node_ids = get_mixed_node_target_ids(mixed_node)
    ctx.logger.debug('Mixed Targets: {0}'.format(mixed_target_node_ids))

    # Get the mixed iaas nodes plan for the possible targets
    plans = mixed_node.properties.get('PLANS')
    ctx.logger.debug('Plans: {0}'.format(plans))

    # Assign delta while we haven't assigned it all
    # or if somehow the target list is empty
    while delta_copy > 0 or len(mixed_target_node_ids) > 0:
        target_node_id = mixed_target_node_ids.pop(0)
        instances_of_node = client.node_instances.list(node_id=target_node_id)

        # Update the lock on everything first.
        instances_of_node_with_lock = lock_or_unlock_node(instances_of_node)
        for node_instance in instances_of_node_with_lock:
            ni = client.node_instances.get(node_instance.id)
            new_runtime_props = node_instance.runtime_properties
            ctx.logger.debug('Changing lock on node instance: {0} {1}'.format(
                ni.id, ni.runtime_properties.get('locked')))
            ctx.logger.debug('\nTHE WHOLE THING: {0}'.format(ni))
            client.node_instances.update(node_instance_id=ni.id,
                                         state=ni.state,
                                         runtime_properties=new_runtime_props,
                                         version=ni.version)

        # If the node is locked,
        # skip it for this iteration of the the while loop.
        if check_if_node_is_locked(instances_of_node):
            ctx.logger.debug('Node is locked: {0}'.format(target_node_id))
            mixed_target_node_ids.append(target_node_id)
            continue

        target_node_plan = plans.get(target_node_id)
        target_node_count = get_latest_node_instance_count(ctx,
                                                           target_node_id,
                                                           modification_data)

        # If the node is at capacity, skip it.
        # No more scaling or bursting this node.
        # Notice we do not do "mixed_target_node_ids.append(target_node_id)"
        if target_node_count >= target_node_plan.get('capacity', float('inf')):
            ctx.logger.debug(
                'Node is over capacity: {0}'.format(target_node_id))
            continue

        # If the node is constrained by other nodes, skip it.
        elif check_target_is_constrained(ctx,
                                         target_node_plan.get('constraints')):
            ctx.logger.debug('Node is constrained: {0}'.format(target_node_id))
            mixed_target_node_ids.append(target_node_id)
            continue

        # At this stage we add the node to the deployment_modification
        # only if it is not locked, over-capacity, or constrained.
        ctx.logger.debug('Adding node to plan: {0}'.format(target_node_id))
        mixed_node_count = \
            get_latest_node_instance_count(ctx,
                                           scalable_entity_name,
                                           modification_data)
        modification_data.update(
            {
                scalable_entity_name: {INSTANCES: mixed_node_count + 1},
                target_node_id: {INSTANCES: target_node_count + 1}
            }
        )
        ctx.logger.debug(
            'Updated Modification Data {0}'.format(modification_data))

        # Decrement the delta so that we know how many instances we have added
        delta_copy -= 1

        # We add the node back to the list,
        # so that it can be incremented again if necessary.
        mixed_target_node_ids.append(target_node_id)

    return modification_data
