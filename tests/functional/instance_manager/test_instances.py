#
# -----------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -----------------------------------------------------------------------------
"""
Instance manager tests.
"""
import os
import subprocess
import time
import unittest

from libcodechecker.server import instance_manager

from libtest import env
from . import EVENT_1, EVENT_2, EVENT_3
from . import start_server


def run_cmd(cmd):
    print(cmd)
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE)

    out, _ = proc.communicate()
    print(out)
    return proc.returncode


class Instances(unittest.TestCase):
    """
    Server instance manager tests.
    """

    def setUp(self):
        # Get the test workspace used to tests.
        self._test_workspace = os.environ['TEST_WORKSPACE']

        test_class = self.__class__.__name__
        print('Running ' + test_class + ' tests in ' + self._test_workspace)

    def testServerStart(self):
        """Started server writes itself to instance list."""

        test_cfg = env.import_test_cfg(self._test_workspace)
        codechecker_1 = test_cfg['codechecker_1']
        start_server(codechecker_1, test_cfg, EVENT_1)

        instance = [i for i in instance_manager.list()
                    if i['port'] == codechecker_1['viewer_port'] and
                    i['workspace'] == self._test_workspace]

        self.assertNotEqual(instance, [],
                            "The started server did not register itself to the"
                            " instance list.")

    def testServerStartSecondary(self):
        """Another started server appends itself to instance list."""

        test_cfg = env.import_test_cfg(self._test_workspace)
        codechecker_1 = test_cfg['codechecker_1']
        codechecker_2 = test_cfg['codechecker_2']
        start_server(codechecker_2, test_cfg, EVENT_2)

        # Workspaces must match, servers were started in the same workspace.
        instance_workspaces = [i['workspace'] for i in instance_manager.list()
                               if i['workspace'] == self._test_workspace]

        self.assertEqual(len(instance_workspaces), 2,
                         "Two servers in the same workspace but the workspace"
                         " was not found twice in the instance list.")

        # Exactly one server should own each port generated
        instance_ports = [i['port'] for i in instance_manager.list()
                          if i['port'] == codechecker_1['viewer_port'] or
                          i['port'] == codechecker_2['viewer_port']]

        self.assertEqual(len(instance_ports), 2,
                         "The ports for the two started servers were not found"
                         " in the instance list.")

    def testShutdownRecordKeeping(self):
        """Test that one server's shutdown keeps the other records."""

        # NOTE: Do NOT rename this method. It MUST come lexicographically
        # AFTER testServerStartSecondary, because we shut down a server started
        # by the aforementioned method.

        # Kill the second started server.
        EVENT_2.set()

        # Give the server some grace period to react to the kill command.
        time.sleep(5)

        test_cfg = env.import_test_cfg(self._test_workspace)
        codechecker_1 = test_cfg['codechecker_1']
        codechecker_2 = test_cfg['codechecker_2']

        instance_1 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_1['viewer_port'] and
                      i['workspace'] == self._test_workspace]
        instance_2 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_2['viewer_port'] and
                      i['workspace'] == self._test_workspace]

        self.assertNotEqual(instance_1, [],
                            "The stopped server deleted another server's "
                            "record from the instance list!")

        self.assertEqual(instance_2, [],
                         "The stopped server did not disappear from the"
                         " instance list.")

    def testShutdownTerminateByCmdline(self):
        """Tests that the command-line command actually kills the server,
        and that it does not kill anything else."""

        # NOTE: Yet again keep the lexicographical flow, no renames!

        test_cfg = env.import_test_cfg(self._test_workspace)
        codechecker_1 = test_cfg['codechecker_1']
        codechecker_2 = test_cfg['codechecker_2']
        start_server(codechecker_2, test_cfg, EVENT_3)

        # Kill the server, but yet again give a grace period.
        self.assertEqual(0, run_cmd([env.codechecker_cmd(),
                                     'server', '--stop',
                                     '--view-port',
                                     str(codechecker_2['viewer_port']),
                                     '--workspace',
                                     self._test_workspace]),
                         "The stop command didn't return exit code 0.")
        time.sleep(5)

        # Check if the remaining server is still there,
        # we need to make sure that --stop only kills the specified server!
        instance_1 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_1['viewer_port'] and
                      i['workspace'] == self._test_workspace]
        instance_2 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_2['viewer_port'] and
                      i['workspace'] == self._test_workspace]

        self.assertNotEqual(instance_1, [],
                            "The stopped server deleted another server's "
                            "record from the instance list!")

        self.assertEqual(instance_2, [],
                         "The stopped server did not disappear from the"
                         " instance list.")

        # Kill the first server via cmdline too.
        self.assertEqual(0, run_cmd([env.codechecker_cmd(),
                                     'server', '--stop',
                                     '--view-port',
                                     str(codechecker_1['viewer_port']),
                                     '--workspace',
                                     self._test_workspace]),
                         "The stop command didn't return exit code 0.")
        time.sleep(5)

        instance_1 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_1['viewer_port'] and
                      i['workspace'] == self._test_workspace]
        instance_2 = [i for i in instance_manager.list()
                      if i['port'] == codechecker_2['viewer_port'] and
                      i['workspace'] == self._test_workspace]

        self.assertEqual(instance_1, [],
                         "The stopped server did not disappear from the"
                         " instance list.")

        self.assertEqual(instance_2, [],
                         "The stopped server made another server's record "
                         "appear in the instance list.")
