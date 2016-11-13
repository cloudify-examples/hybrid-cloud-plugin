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
from cloudify_rest_client.client import CloudifyClient
from cloudify.workflows.workflow_context import (
    LocalCloudifyWorkflowContextHandler,
    CloudifyWorkflowContextInternal,
    CloudifyWorkflowNode,
    CloudifyWorkflowNodeInstance)
from cloudify.utils import setup_logger
from cloudify.test_utils import workflow_test
from dp_plugin.burst import burst_up, burst_down

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
        self._endpoint = storage
        self._local_task_thread_pool_size = 1
        self._task_retry_interval = 1
        self._task_retries = 1
        self._subgraph_retries = 1
        self._mock_context_logger = \
            setup_logger('mock-context-logger')
        handler = \
            LocalCloudifyWorkflowContextHandler(self, storage)
        self.internal = \
            CloudifyWorkflowContextInternal(self, handler)
        raw_nodes = storage.get_nodes()
        raw_node_instances = storage.get_node_instances()
        self._nodes = dict(
            (node.id, CloudifyWorkflowNode(self, node, self))
            for node in raw_nodes)
        self._node_instances = dict(
            (instance.id, CloudifyWorkflowNodeInstance(
                self, self._nodes[instance.node_id], instance,
                self))
            for instance in raw_node_instances)

    @property
    def logger(self):
        return self._mock_context_logger

    def get_node(self, node_id):
        return self._nodes.get(node_id)


class TestBurst(testtools.TestCase):

    def get_mock_workflow_context(self, _storage):
        cloudify_workflow_context = \
            MockCloudifyWorkflowContext(_storage)
        return cloudify_workflow_context

    def mock_cloudify_client(self, _storage):
        client = CloudifyClient()
        client.nodes = _storage.nodes
        client.node_instances = _storage.node_instances
        return client

    burst_blueprint_path = os.path.join('resources', 'blueprint.yaml')

    def get_dp_node_group_ids(self, dp_managing_node_rs):
        return [rs.get('target_id') for rs in dp_managing_node_rs]

    def get_deployment_plans(self, dp_managing_node):
        return dp_managing_node.properties.get(PLANS)

    def set_up_dp_nodes_group(self,
                              cfy_local_env,
                              dp_nodes_group_ids,
                              dp_node_plans):
        dp_nodes_group = {}
        for dp_node_id in dp_nodes_group_ids:
            this_dp_node = cfy_local_env.storage.get_node(dp_node_id)
            dp_nodes_group.update({
                this_dp_node.id: {
                    'count': int(this_dp_node.number_of_instances),
                    'capacity': dp_node_plans.get(
                        this_dp_node.id, {}).get('capacity', {}),
                    'constraints': dp_node_plans.get(
                        this_dp_node.id, {}).get('constraints', {})
                }
            })
        return dp_nodes_group

    @workflow_test(blueprint_path=burst_blueprint_path)
    def test_burst_up(self, cfy_local):
        dp_managing_node = cfy_local.storage.get_node('dp_compute')
        ctx = self.get_mock_workflow_context(cfy_local.storage)
        number_of_new_instances = 2
        mixed_target_node_ids = \
            self.get_dp_node_group_ids(dp_managing_node['relationships'])
        plans = self.get_deployment_plans(dp_managing_node)
        modification_data = \
            {dp_managing_node.id: {'instances':
                                   dp_managing_node.number_of_instances}}
        with mock.patch('dp_plugin.burst.manager_client') as \
                self.mock_cloudify_client:
            burst_up_modification_data = \
                burst_up(ctx,
                         dp_managing_node.id,
                         number_of_new_instances,
                         mixed_target_node_ids,
                         plans,
                         modification_data)
        self.assertEqual(
            dp_managing_node.number_of_instances + number_of_new_instances,
            burst_up_modification_data.get(
                dp_managing_node.id).get('instances')
        )
        dp_compute_1 = cfy_local.storage.get_node('cloud_1_compute')
        self.assertEqual(
            dp_compute_1.number_of_instances + number_of_new_instances,
            burst_up_modification_data.get('cloud_1_compute').get('instances')
        )

    @workflow_test(blueprint_path=burst_blueprint_path)
    def test_burst_down(self, cfy_local):
        dp_managing_node = cfy_local.storage.get_node('dp_compute')
        ctx = self.get_mock_workflow_context(cfy_local.storage)
        number_of_new_instances = -1
        mixed_target_node_ids = \
            self.get_dp_node_group_ids(dp_managing_node['relationships'])
        modification_data = \
            {dp_managing_node.id: {'instances':
                                   dp_managing_node.number_of_instances}}
        with mock.patch('dp_plugin.burst.manager_client') as \
                self.mock_cloudify_client:
            burst_up_modification_data = \
                burst_down(ctx,
                           dp_managing_node.id,
                           number_of_new_instances,
                           mixed_target_node_ids,
                           modification_data)
        self.assertEqual(
            dp_managing_node.number_of_instances + number_of_new_instances,
            burst_up_modification_data.get(
                dp_managing_node.id).get('instances')
        )
        dp_compute_1 = cfy_local.storage.get_node('cloud_1_compute')
        self.assertEqual(
            dp_compute_1.number_of_instances + number_of_new_instances,
            burst_up_modification_data.get('cloud_1_compute').get('instances')
        )
