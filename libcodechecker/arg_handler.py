# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------
"""
Handle old-style subcommand invocation.
"""
import errno
import json
import os
import socket
import sys

from libcodechecker import client
from libcodechecker import debug_reporter
from libcodechecker import generic_package_context
from libcodechecker import generic_package_suppress_handler
from libcodechecker import host_check
from libcodechecker import session_manager
from libcodechecker import util
from libcodechecker.analyze import analyzer_env
from libcodechecker.analyze.analyzers import analyzer_types
from libcodechecker.database_handler import SQLServer
from libcodechecker.logger import LoggerFactory
from libcodechecker.server import client_db_access_server
from libcodechecker.server import instance_manager

LOG = LoggerFactory.get_new_logger('ARG_HANDLER')


# TODO: Will be replaced wholly by libcodechecker/checkers.py.
def handle_list_checkers(args):
    """
    List the supported checkers by the analyzers.
    List the default enabled and disabled checkers in the config.
    """
    context = generic_package_context.get_context()
    # If nothing is set, list checkers for all supported analyzers.
    analyzers = args.analyzers or analyzer_types.supported_analyzers
    enabled_analyzers, _ = analyzer_types\
        .check_supported_analyzers(analyzers, context)
    analyzer_environment = analyzer_env.get_check_env(
        context.path_env_extra,
        context.ld_lib_path_extra)

    for ea in enabled_analyzers:
        if ea not in analyzer_types.supported_analyzers:
            LOG.error('Unsupported analyzer ' + str(ea))
            sys.exit(1)

    analyzer_config_map = \
        analyzer_types.build_config_handlers(args,
                                             context,
                                             enabled_analyzers)

    for ea in enabled_analyzers:
        # Get the config.
        config_handler = analyzer_config_map.get(ea)
        source_analyzer = \
            analyzer_types.construct_analyzer_type(ea,
                                                   config_handler,
                                                   None)

        checkers = source_analyzer.get_analyzer_checkers(config_handler,
                                                         analyzer_environment)

        default_checker_cfg = context.default_checkers_config.get(
            ea + '_checkers')

        analyzer_types.initialize_checkers(config_handler,
                                           checkers,
                                           default_checker_cfg)
        for checker_name, value in config_handler.checks().items():
            enabled, description = value
            if enabled:
                print(' + {0:50} {1}'.format(checker_name, description))
            else:
                print(' - {0:50} {1}'.format(checker_name, description))


def handle_server(args):
    """
    Starts the report viewer server.
    """
    if not host_check.check_zlib():
        sys.exit(1)

    workspace = args.workspace

    if (args.list or args.stop or args.stop_all) and \
            not (args.list ^ args.stop ^ args.stop_all):
        print("CodeChecker server: error: argument -l/--list and -s/--stop"
              "and --stop-all are mutually exclusive.")
        sys.exit(2)

    if args.list:
        instances = instance_manager.list()

        instances_on_multiple_hosts = any(True for inst in instances
                                          if inst['hostname'] !=
                                          socket.gethostname())
        if not instances_on_multiple_hosts:
            rows = [('Workspace', 'View port')]
        else:
            rows = [('Workspace', 'Computer host', 'View port')]

        for instance in instance_manager.list():
            if not instances_on_multiple_hosts:
                rows.append((instance['workspace'], str(instance['port'])))
            else:
                rows.append((instance['workspace'],
                             instance['hostname']
                             if instance['hostname'] != socket.gethostname()
                             else '',
                             str(instance['port'])))

        print("Your running CodeChecker servers:")
        print(util.twodim_to_table(rows))
        sys.exit(0)
    elif args.stop or args.stop_all:
        for i in instance_manager.list():
            # A STOP only stops the server associated with the given workspace
            # and view-port.
            if i['hostname'] != socket.gethostname() or (
                args.stop and not (i['port'] == args.view_port and
                                   os.path.abspath(i['workspace']) ==
                                   os.path.abspath(workspace))):
                continue

            try:
                util.kill_process_tree(i['pid'])
                LOG.info("Stopped CodeChecker server running on port {0} "
                         "in workspace {1} (PID: {2})".
                         format(i['port'], i['workspace'], i['pid']))
            except:
                # Let the exception come out if the commands fail
                LOG.error("Couldn't stop process PID #" + str(i['pid']))
                raise
        sys.exit(0)

    # WARNING
    # In case of SQLite args.dbaddress default value is used
    # for which the is_localhost should return true.
    if util.is_localhost(args.dbaddress) and not os.path.exists(workspace):
        os.makedirs(workspace)

    suppress_handler = generic_package_suppress_handler.\
        GenericSuppressHandler(None)
    if args.suppress is None:
        LOG.warning('No suppress file was given, suppressed results will '
                    'be only stored in the database.')
    else:
        if not os.path.exists(args.suppress):
            LOG.error('Suppress file ' + args.suppress + ' not found!')
            sys.exit(1)

    context = generic_package_context.get_context()
    context.codechecker_workspace = workspace
    session_manager.SessionManager.CodeChecker_Workspace = workspace
    context.db_username = args.dbusername

    check_env = analyzer_env.get_check_env(context.path_env_extra,
                                           context.ld_lib_path_extra)

    sql_server = SQLServer.from_cmdline_args(args,
                                             context.migration_root,
                                             check_env)
    conn_mgr = client.ConnectionManager(sql_server, args.check_address,
                                        args.check_port)
    if args.check_port:
        LOG.debug('Starting CodeChecker server and database server.')
        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)
        conn_mgr.start_report_server()
    else:
        LOG.debug('Starting database.')
        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)

    # Start database viewer.
    db_connection_string = sql_server.get_connection_string()

    suppress_handler.suppress_file = args.suppress
    LOG.debug('Using suppress file: ' + str(suppress_handler.suppress_file))

    checker_md_docs = os.path.join(context.doc_root, 'checker_md_docs')
    checker_md_docs_map = os.path.join(checker_md_docs,
                                       'checker_doc_map.json')
    with open(checker_md_docs_map, 'r') as dFile:
        checker_md_docs_map = json.load(dFile)

    package_data = {'www_root': context.www_root,
                    'doc_root': context.doc_root,
                    'checker_md_docs': checker_md_docs,
                    'checker_md_docs_map': checker_md_docs_map,
                    'version': context.package_git_tag}

    try:
        client_db_access_server.start_server(package_data,
                                             args.view_port,
                                             db_connection_string,
                                             suppress_handler,
                                             args.not_host_only,
                                             context)
    except socket.error as err:
        if err.errno == errno.EADDRINUSE:
            LOG.error("Server can't be started, maybe the given port number "
                      "({}) is already used. Check the connection "
                      "parameters.".format(args.view_port))
            sys.exit(1)
        else:
            raise


def handle_debug(args):
    """
    Runs a debug command on the buildactions where the analysis
    failed for some reason.
    """
    context = generic_package_context.get_context()

    context.codechecker_workspace = args.workspace
    context.db_username = args.dbusername

    check_env = analyzer_env.get_check_env(context.path_env_extra,
                                           context.ld_lib_path_extra)

    sql_server = SQLServer.from_cmdline_args(args,
                                             context.migration_root,
                                             check_env)
    sql_server.start(context.db_version_info, wait_for_start=True, init=False)

    debug_reporter.debug(context, sql_server.get_connection_string(),
                         args.force)
