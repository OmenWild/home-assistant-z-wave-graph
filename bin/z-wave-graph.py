#! /usr/bin/env python3

import argparse
import datetime
import json
import os.path
import re
import sys


def need(what):
    print("Error unable to import the module `%s', please pip install it" % what, end='')
    if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        print(" from WITHIN your virtual environment", end='')
    print(".\n")
    sys.exit(1)


try:
    import networkx as nx
except ImportError:
    need('networkx')

import homeassistant.config
import homeassistant.remote as remote
import homeassistant.const


class Node(object):
    def __init__(self, attrs):
        self.attrs = attrs
        self.rank = None

        try:
            self.neighbors = sorted(self.neighbors)
        except KeyError:
            self.neighbors = []

        self.primary_controller = False
        try:
            if 'primaryController' in self.capabilities:
                # Make any Z-Wave node that is a primaryController stand out.
                self.primary_controller = True
        except KeyError:
            pass

        self.forwarder = True
        if self.is_awake == False or \
                self.is_ready == False or \
                self.is_failed == True or \
                'listening' not in self.capabilities:
            self.forwarder = False


    def __getattr__(self, name):
        return self.attrs[name]


    @property
    def id(self):
        return self.node_id


    def __str__(self):
        if self.primary_controller:
            return "Z-Wave Hub\n%s" % datetime.datetime.now().strftime('%b %d\n%H:%M')
        else:
            return ("%s%s" % (self.friendly_name, '!!!' if self.is_failed else '')).replace(' ', "\n")


    def title(self):
        title = ""

        if self.is_failed:
            title += "<b>FAILED: </b>"

        title += "<b>%s</b><br/>" % self.friendly_name

        title += "Node: %s" % self.node_id

        if self.is_zwave_plus:
            title += "<b>+</b>"

        title += "<br/>Product Name: %s" % self.product_name

        try:
            title += "<br/>Battery: %s%%" % self.battery_level
        except KeyError:
            pass

        return title


    def __iter__(self):
        yield self.neighbors


class Nodes(object):
    def __init__(self):
        self.nodes = {}
        self.primary_controller = None
        self.ranked = False


    def add(self, attrs):
        node = Node(attrs)
        self.nodes[node.node_id] = node
        if node.primary_controller:
            self.primary_controller = node


    def create_ranks(self):
        # Dump everything into networkx to get depth
        G = nx.Graph()

        # First, add all the nodes
        G.add_nodes_from(self.nodes.keys())

        # Next, add all the edges
        for key, node in self.nodes.items():
            for neighbor in node.neighbors:
                G.add_edge(key, neighbor)

        # Finally, find the shortest path
        for key, node in self.nodes.items():
            try:
                node.shortest = [p for p in nx.all_shortest_paths(G, key, 1)]
                node.rank = len(node.shortest[0])
            except (nx.exception.NetworkXNoPath, IndexError):
                # Unconnected devices (remotes) may have no current path.
                node.rank = 1
                node.shortest = []

        self.ranked = True


    def __iter__(self):
        # Iterate over all the nodes, rank by rank.

        if not self.ranked:
            self.create_ranks()

        # Z-Wave networks can be 6 layers deep, the hub, up to 4 hops, and the destination.
        for rank in [1, 2, 3, 4, 5, 6]:
            for node in sorted(filter(lambda x: x.rank == rank, self.nodes.values()), key=lambda k: k.node_name):
                yield node


class ZWave(object):
    def __init__(self, config, args):
        self.args = args
        self.nodes = Nodes()
        self.json = {'nodes': [], 'edges': []}

        self.haconf = homeassistant.config.load_yaml_config_file(config)

        self.directory = os.path.join(os.path.dirname(config), 'www')
        self.filename = 'z-wave-graph.json'

        # API connection necessities.
        api_password = None
        base_url = 'http://localhost'
        port = homeassistant.const.SERVER_PORT

        if self.haconf['http'] is not None and 'base_url' in self.haconf['http']:
            base_url = self.haconf['http']['base_url']

        if self.haconf['http'] is not None and 'api_password' in self.haconf['http']:
            api_password = str(self.haconf['http']['api_password'])

        # If the base_url ends with a port, then strip it and set the port.
        # remote.API adds the default port if port= is not set.
        m = re.match(r'(^.*)(:(\d+))$', base_url)
        if m:
            base_url = m.group(1)
            port = m.group(3)

        self.api = remote.API(base_url, api_password, port=port)
        if remote.validate_api(self.api).value != 'ok':
            print("Error, unable to connect to the API: %s" % remote.validate_api(self.api))
            sys.exit(1)

        self._get_entities()

        if self.args.debug:
            self.dump_nodes()

        self._build_dot()


    def dump_nodes(self):
        rank = -1
        for node in self.nodes:
            if node.rank != rank:
                print("\n\nvvvvvvvvvv %d vvvvvvvvvv\n" % node.rank)
                rank = node.rank

            print("%d => %s" % (node.id, node.neighbors))
            for path in node.shortest:
                print("   %s" % path)
            print()


    def add(self, node):
        return self.nodes.add(node)


    def _get_entities(self):
        entities = remote.get_states(self.api)
        for entity in entities:
            if entity.entity_id.startswith('zwave'):
                self.add(entity.attributes)


    def _build_dot(self):
        for node in self.nodes:
            config = {
                'label': str(node),
                'title': node.title(),
                'group': 'Layer %d' % node.rank,
            }
            if 'battery_level' in node.attrs:
                config['shape'] = 'box'
            else:
                config['shape'] = 'circle'

            if node.primary_controller:
                config['borderWidth'] = 2
                config['fixed'] = True

            self.json['nodes'].append({'id': node.id, **config})

        for node in self.nodes:
            for path in node.shortest:
                for edge in path[1:2]:  # Only graph the first hop in each node.

                    config = {}
                    if node.id == edge:
                        # Skip myself
                        continue

                    if not self.nodes.nodes[edge].forwarder:
                        # Skip edges that go through devices that look like they don't forward.
                        continue

                    if node.averageRequestRTT > 0:
                        config['value'] = 1.0 / node.averageRequestRTT
                    config['title'] = '%s: %dms' % ('averageRequestRTT', node.averageRequestRTT)

                    self.json['edges'].append({'from': node.id, 'to': edge, **config})


    def render(self):
        if self.args.debug:
            print(self.json)

        fp = os.path.join(self.directory, self.filename)
        with open(fp, 'w') as outfile:
            json.dump(self.json, outfile, indent=2, sort_keys=True)


if __name__ == '__main__':
    """Generate graph of Home Assistant Z-Wave devices."""
    to_check = ['~/.config/', '~/config/', '~/.homeassistant/', '~/homeassistant/', '/config/']
    config = None

    for check in to_check:
        expanded = os.path.expanduser(os.path.join(check, 'configuration.yaml'))
        if os.path.isfile(expanded):
            config = expanded

    parser = argparse.ArgumentParser(description='Generate a Z-Wave mesh from your Home Assistant system.')
    parser.add_argument('--config', help='path to configuration.yaml')
    parser.add_argument('--debug', action="store_true", dest='debug', default=False, help='print debug output')
    args = parser.parse_args()

    if not config:
        if 'config' not in args or not args.config:
            raise ValueError("Unable to automatically find configuration.yaml, you have to specify it with -c/--config")

        to_check = [args.config, os.path.join(args.config, 'configuration.yaml')]

        for check in to_check:
            expanded = os.path.expanduser(check)
            if expanded and os.path.isfile(expanded):
                config = expanded

        if not config:
            raise ValueError("Unable to find configuration.yaml in specified location.")

    zwave = ZWave(config, args)
    zwave.render()
