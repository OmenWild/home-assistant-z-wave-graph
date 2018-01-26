#! /usr/bin/env python3

import argparse
import datetime
import json
import os.path
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


class Node(object):
    def __init__(self, attrs):
        self.attrs = attrs
        self.rank = None

        self.node_id = self.attrs['node_id']
        try:
            self.neighbors = sorted(self.attrs['neighbors'])
        except KeyError:
            self.neighbors = []

        self.primary_controller = False
        try:
            if 'primaryController' in self.attrs['capabilities']:
                # Make any Z-Wave node that is a primaryController stand out.
                self.primary_controller = True
        except KeyError:
            pass

        self.forwarder = True
        if self.attrs['is_awake'] == 'false' or \
                self.attrs['is_ready'] == 'false' or \
                self.attrs['is_failed'] == 'true' or \
                'listening' not in self.attrs['capabilities']:
            self.forwarder = False

    @property
    def id(self):
        return self.node_id

    def __str__(self):
        if self.rank == 1:
            return "Z-Wave Hub\n%s" % datetime.datetime.now().strftime('%b %d\n%T')
        else:
            return self.attrs['friendly_name'].replace(' ', "\n")

    def title(self):
        title = "<b>%s</b><br/>" % self.attrs['friendly_name']

        title += "Node: %s" % self.node_id

        if self.attrs['is_zwave_plus']:
            title += "<b>+</b>"

        title += "<br/>Product Name: %s" % self.attrs['product_name']

        try:
            title += "<br/>Battery: %s%%" % self.attrs['battery_level']
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
                node.rank = len(nx.shortest_path(G, 1, key))
                node.shortest = [p for p in nx.all_shortest_paths(G, 1, key)]
                node.rank = len(node.shortest[0])
            except (nx.exception.NetworkXNoPath, IndexError):
                # Unconnected devices (remotes) may have no current path.
                node.rank = 0

        self.ranked = True

    def __iter__(self):
        # Iterate over all the nodes, regardless of rank.
        if not self.ranked:
            self.create_ranks()

        for rank in [1, 2, 3, 4, 5, 6]:
            for key in sorted(self.nodes):
                node = self.nodes[key]
                if node.rank == rank:
                    yield node


class ZWave(object):
    def __init__(self, config, args):
        self.nodes = Nodes()
        self.json = {'nodes': [], 'edges': []}

        self.neighbors = {}
        self.primary_controller = []

        self.haconf = homeassistant.config.load_yaml_config_file(config)

        self.directory = os.path.join(os.path.dirname(config), 'www')
        self.filename = 'z-wave-graph'

        api_password = None
        base_url = 'localhost'

        if self.haconf['http'] is not None and 'base_url' in self.haconf['http']:
            base_url = self.haconf['http']['base_url']
            if ':' in base_url:
                base_url = base_url.split(':')[0]

        if base_url != 'localhost':
            if 'api_password' in self.haconf['http']:
                api_password = str(self.haconf['http']['api_password'])

        self.api = remote.API(base_url, api_password, port=args.port, use_ssl=args.ssl)

        self._get_entities()
        self._build_dot()

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

            if node.rank == 1:
                config['borderWidth'] = 2
                config['fixed'] = True

            self.json['nodes'].append({'id': node.id, **config})

        # Tracked graphed connections to eliminate duplicates
        graphed = {}

        for node in self.nodes:
            for path in node.shortest:
                for edge in path[-2:]:
                    config = {}
                    if node.id == edge:
                        continue

                    if not self.nodes.nodes[edge].forwarder:
                        # Skip edges that go through devices that look like they don't forward.
                        continue

                    config['value'] = 5 - node.rank

                    if (node.id, edge) not in graphed and (edge, node.id) not in graphed:
                        self.json['edges'].append({'from': node.id, 'to': edge, **config})
                        graphed[(node.id, edge)] = True

    def render(self):
        # self.dot.render(filename=self.filename, directory=self.directory
        fp = os.path.join(self.directory, self.filename + '.json')
        with open(fp, 'w') as outfile:
            pretty = json.dump(self.json, outfile, indent=4, sort_keys=True)


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
    parser.add_argument('--port', type=int, default=8123, help='use if you run HA on a non-standard port')
    parser.add_argument('--no-ssl', action="store_false", dest='ssl', default=True, help='force a non-SSL API connection')

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
