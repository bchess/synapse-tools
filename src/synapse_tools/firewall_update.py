# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import os.path
import time
from collections import defaultdict

from inotify.adapters import Inotify
from inotify.constants import IN_MODIFY
from inotify.constants import IN_MOVED_TO

from synapse_tools import configure_synapse
from paasta_tools.marathon_tools import load_marathon_service_config
from paasta_tools.marathon_tools import marathon_services_running_here
from paasta_tools.utils import DEFAULT_SOA_DIR
from paasta_tools.utils import load_system_paasta_config


UPDATE_SECS = 5
SYNAPSE_SERVICE_DIR = b'/var/run/synapse/services'


def smartstack_dependencies_of_running_firewalled_services(soa_dir=DEFAULT_SOA_DIR):
    dependencies_to_services = defaultdict(list)

    cluster = load_system_paasta_config().get_cluster()
    for service, instance, port in marathon_services_running_here():  # TODO: + chronos
        config = load_marathon_service_config(service, instance, cluster, load_deployments=False, soa_dir=soa_dir)

        outbound_firewall = config.get_outbound_firewall()
        if not outbound_firewall:
            continue

        dependencies = config.get_dependencies()

        smartstack_dependencies = [d['smartstack'] for d in dependencies if d.get('smartstack')]
        for smartstack_dependency in smartstack_dependencies:
            dependencies_to_services[smartstack_dependency].append((service, instance))

    return dependencies_to_services


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Monitor synapse changes and update service firewall rules')
    parser.add_argument('-c', '--synapse-tools-config', dest="synapse_tools_config",
                        default='/etc/synapse/synapse-tools.conf.json',
                        help="Path to synapse tools config (default %(default)s)")
    parser.add_argument('-d', '--soa-dir', dest="soa_dir", metavar="soa_dir",
                        default=DEFAULT_SOA_DIR,
                        help="define a different soa config directory (default %(default)s)")
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true')

    args = parser.parse_args(argv)
    return args


def main(argv=None):
    args = parse_args(argv)
    synapse_config = configure_synapse.get_config(args.synapse_tools_config)
    synapse_service_dir = synapse_config['file_output_path']

    services_by_dependencies = smartstack_dependencies_of_running_firewalled_services(soa_dir=args.soa_dir)
    services_by_dependencies_time = time.time()

    inotify = Inotify()
    inotify.add_watch(synapse_service_dir, IN_MOVED_TO | IN_MODIFY)

    for event in inotify.event_gen():
        if services_by_dependencies_time + UPDATE_SECS < time.time():
            # only update every N seconds
            services_by_dependencies = smartstack_dependencies_of_running_firewalled_services(soa_dir=args.soa_dir)
            services_by_dependencies_time = time.time()
            if args.verbose:
                print(dict(services_by_dependencies))

        if event is None:
            continue

        filename = event[3]
        try:
            service_instance, suffix = os.path.splitext(filename)
            if suffix != '.json':
                continue
        except ValueError:
            continue

        services_to_update = services_by_dependencies.get(service_instance, ())
        for service_to_update in services_to_update:
            pass  # TODO: update the iptables
            if args.verbose:
                print('Update ', service_to_update)
