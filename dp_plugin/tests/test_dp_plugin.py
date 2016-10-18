########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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

import os
import mock
import testtools
from cloudify.mocks import MockContext
from cloudify.workflows.workflow_context import (
    LocalCloudifyWorkflowContextHandler,
    CloudifyWorkflowContextInternal)
from cloudify.utils import setup_logger
from cloudify.test_utils import workflow_test
from dp_plugin.workflows import (update_deployment_modification,
                                 assign_delta_to_nodes,
                                 build_modification_data_profile)

WORKFLOW_NAME = 'scale_or_burst'
INSTALL_NI = 'cloudify.plugins.lifecycle.install_node_instances'
START_MOD = 'cloudify.workflows.workflow_context.' \
            'WorkflowDeploymentContext.start_modification'

PLAN_RS = 'cloudify.dp.relationships.plans'
PLANS = 'deployment_plans'


class MockCloudifyWorkflowContext(MockContext):

    def __init__(self, storage):
        self._context = {}
        self.local = True
        self._local_task_thread_pool_size = 1
        self._task_retry_interval = 1
        self._task_retries = 1
        self._subgraph_retries = 1
        self._mock_context_logger = setup_logger('mock-context-logger')
        handler = LocalCloudifyWorkflowContextHandler(self, storage)
        self.internal = CloudifyWorkflowContextInternal(self, handler)
        self._nodes = storage.get_nodes()
        self._instances = storage.get_node_instances()

    @property
    def logger(self):
        return self._mock_context_logger

    def get_node(self, node_id):
        for _node in self._nodes:
            if _node.get('id') ==  node_id:
                return _node
        return None

class TestBurst(testtools.TestCase):

    def get_mock_workflow_context(self, _storage):
        cloudify_workflow_context = MockCloudifyWorkflowContext(_storage)
        return cloudify_workflow_context

    burst_blueprint_path = os.path.join('resources', 'blueprint.yaml')

    def get_dp_node_group_ids(self, dp_managing_node_rs):
        return [rs.get('target_id') for rs in dp_managing_node_rs]

    def get_deployment_plans(self, dp_managing_node):
        return dp_managing_node.properties.get(PLANS)

    def set_up_dp_nodes_group(self, cfy_local_env, dp_nodes_group_ids, dp_node_plans):
        dp_nodes_group = {}
        for dp_node_id in dp_nodes_group_ids:
            this_dp_node = cfy_local_env.storage.get_node(dp_node_id)
            dp_nodes_group.update({
                this_dp_node.id: {
                    'count': int(this_dp_node.number_of_instances),
                    'capacity': dp_node_plans.get(this_dp_node.id, {}).get('capacity', {}),
                    'constraints': dp_node_plans.get(this_dp_node.id, {}).get('constraints', {})
                }
            })
        return dp_nodes_group


    # @workflow_test(blueprint_path=burst_blueprint_path)
    # def test_locking(self, cfy_local):
    #     dp_managing_node = cfy_local.storage.get_node('dp_compute')
    #     dp_node_group_ids = self.get_dp_node_group_ids(dp_managing_node['relationships'])
    #     dp_node_plans = self.get_deployment_plans(dp_managing_node)
    #     dp_nodes_group = self.set_up_dp_nodes_group(cfy_local,
    #                                                 dp_node_group_ids,
    #                                                 dp_node_plans)
    #
    #     for x in range(len(dp_nodes_group) * 25):
    #         for dp_node_id in dp_node_group_ids:
    #             dp_nodes_group = temporarily_lock_node(dp_nodes_group, dp_node_id)
    #             locked_nodes = []
    #             for _dp_node_id, _dp_node in dp_nodes_group.items():
    #                 if _dp_node.get('locked'):
    #                     locked_nodes.append((_dp_node_id, _dp_node.get('locked')))
    #             self.assertIsNot(0, len(locked_nodes))


    @workflow_test(blueprint_path=burst_blueprint_path)
    def test_update_deployment_modification(self, cfy_local):
        dp_managing_node = cfy_local.storage.get_node('dp_compute')
        number_of_old_instances = dp_managing_node.number_of_instances
        ctx = self.get_mock_workflow_context(cfy_local.storage)
        number_of_new_instances = 2
        modification_data = {}
        modification_data = update_deployment_modification(ctx,
                                                           number_of_new_instances,
                                                           dp_managing_node,
                                                           modification_data)
        self.assertEqual(number_of_old_instances + number_of_new_instances,
                         modification_data.get('dp_compute').get('instances'))

    @workflow_test(blueprint_path=burst_blueprint_path)
    def test_assign_delta_to_nodes(self, cfy_local):
        dp_managing_node = cfy_local.storage.get_node('dp_compute')
        dp_node_group_ids = self.get_dp_node_group_ids(dp_managing_node['relationships'])
        dp_node_plans = self.get_deployment_plans(dp_managing_node)
        dp_nodes_group = self.set_up_dp_nodes_group(cfy_local,
                                                    dp_node_group_ids,
                                                    dp_node_plans)
        ctx = self.get_mock_workflow_context(cfy_local.storage)
        test_round = 20
        number_of_new_instances = test_round
        _modification_data = {
            dp_managing_node.id: {
                'instances': dp_managing_node.number_of_instances + number_of_new_instances
            }
        }

        while number_of_new_instances > 0:
            _dp_test_node_id = dp_node_group_ids.pop(0)
            _dp_test_node = cfy_local.storage.get_node(_dp_test_node_id)
            _assigned_node_in_fn, _modification_data, dp_nodes_group = \
                assign_delta_to_nodes(ctx,
                                      _dp_test_node.id,
                                      number_of_new_instances,
                                      _modification_data,
                                      dp_nodes_group)
            number_of_new_instances = number_of_new_instances - _assigned_node_in_fn
            dp_node_group_ids.insert(len(dp_node_group_ids), _dp_test_node_id)

        self.assertEqual(_modification_data.get('cloud_3_compute').get('instances'),
                         dp_nodes_group.get('cloud_3_compute').get('capacity'))
        self.assertEqual(_modification_data.get('cloud_2_compute').get('instances'),
                         dp_nodes_group.get('cloud_2_compute').get('capacity'))

        counted_new_instances = 0
        for key, value in _modification_data.items():
            if dp_managing_node.id not in key:
                counted_new_instances += value.get('instances')
            else:
                dp_node_instances = value.get('instances')

        self.assertEqual(dp_node_instances, counted_new_instances)

    @workflow_test(blueprint_path=burst_blueprint_path)
    @mock.patch('dp_plugin.workflows.get_list_of_dp_node_ids',
                return_value=['cloud_1_compute','cloud_2_compute','cloud_3_compute'])
    def test_build_modification_data_profile(self, cfy_local, *_):
        dp_managing_node = cfy_local.storage.get_node('dp_compute')
        ctx = self.get_mock_workflow_context(cfy_local.storage)
        test_round = 300
        modification_data = build_modification_data_profile(ctx, dp_managing_node, test_round)
        counted_new_instances = 0
        for key, value in modification_data.items():
            if dp_managing_node.id not in key:
                counted_new_instances += value.get('instances')
            else:
                dp_node_instances = value.get('instances')
        self.assertEqual(dp_node_instances, counted_new_instances)
