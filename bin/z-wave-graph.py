#! /usr/bin/env python3

import sys
import argparse
import datetime
import os.path

def need(what):
    print("Error unable to import the module `%s', please pip install it" % what, end='')
    if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        print(" from WITHIN your virtual environment", end='')
    print(".\n")
    sys.exit(1)

try:
    from graphviz import Digraph
except ImportError:
    need('graphviz')

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

        self.id = self.attrs['node_id']
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


    def __str__(self):
        name, extra = self.name()
        return name


    def name(self):
        extra = {}
        if self.primary_controller:
            extra['fillcolor'] = 'chartreuse'
            extra['style'] = "rounded,filled"

        name = self.attrs['friendly_name']

        name += " [%s" % self.id

        if self.attrs['is_zwave_plus']:
            name += "+"
        else:
            name += "-"
        name += "]\n(%s" % self.attrs['product_name']

        try:
            name += ": %s%%" % self.attrs['battery_level']
        except KeyError:
            pass

        name += ")"

        return name, extra


    def __iter__(self):
        yield self.neighbors


class Nodes(object):
    def __init__(self):
        self.nodes = {}
        self.primary_controller = None
        self.ranked = False


    def add(self, attrs):
        node = Node(attrs)
        self.nodes[node.id] = node
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
            except nx.exception.NetworkXNoPath:
                # Unconnected devices (remotes) may have no path.
                node.rank = 0

        self.ranked = True


    def __iter__(self):
        # Iterate over all the nodes, regardless of rank.
        if not self.ranked:
            self.create_ranks()

        for rank in [1, 2, 3, 4]:
            for key in sorted(self.nodes):
                node = self.nodes[key]
                if node.rank == rank:
                    yield node


class ZWave(object):
    def __init__(self, config):
        self.nodes = Nodes()

        self.neighbors = {}
        self.primary_controller = []

        self.haconf = homeassistant.config.load_yaml_config_file(config)

        self.directory = os.path.join(os.path.dirname(config), 'www')
        self.filename = 'z-wave-graph'

        api_password = None
        use_ssl = False
        base_url = 'localhost'

        if self.haconf['http'] is not None and 'base_url' in self.haconf['http']:
            base_url = self.haconf['http']['base_url']
            if ':' in base_url:
                base_url = base_url.split(':')[0]

        if base_url != 'localhost':
            if 'api_password' in self.haconf['http']:
                api_password = str(self.haconf['http']['api_password'])

            if 'ssl_key' in self.haconf['http']:
                use_ssl = True

        self.api = remote.API(base_url, api_password, use_ssl=use_ssl)

        self.dot = Digraph(comment='Home Assistant Z-Wave Graph', format='svg', engine='dot')

        # http://matthiaseisen.com/articles/graphviz/
        self.dot.attr('graph', {
            'label': r'Z-Wave Node Connections\nLast updated: ' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fontsize': '24',
        })

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
            name, extra = node.name()
            extra['penwidth'] = '2'
            if 'battery_level' in node.attrs:
                extra['shape'] = 'polygon'
            self.dot.node(str(node.id), name, extra)

        # Tracked graphed connections to eliminate duplicates
        graphed = {}

        for node in self.nodes:
            for edge in node.neighbors:
                extra = {'dir': 'both'}

                if node.rank == 1:
                    # Connections to the root node get special colors
                    extra['color'] = 'green'
                    extra['penwidth'] = '2'
                elif node.rank == 2:
                    extra['style'] = 'dashed'
                    extra['penwidth'] = '2'
                else:
                    extra['style'] = 'dotted'
                    extra['penwidth'] = '2'

                if (node.id, edge) not in graphed and (edge, node.id) not in graphed:
                    self.dot.edge(str(node.id), str(edge), **extra)
                    graphed[(node.id, edge)] = True


    def render(self):
        self.dot.render(filename=self.filename, directory=self.directory)


if __name__ == '__main__':
    """Generate graph of Home Assistant Z-Wave devices."""
    to_check = ['~/.config/', '~/config/', '~/.homeassistant/', '~/homeassistant/', '/config/']
    config = None

    for check in to_check:
        expanded = os.path.expanduser(os.path.join(check, 'configuration.yaml'))
        if os.path.isfile(expanded):
            config = expanded

    if not config:
        parser = argparse.ArgumentParser()
        parser.add_argument('-c', '--config', help='path to configuration.yaml')
        args = parser.parse_args()

        if 'config' not in args or not args.config:
            raise ValueError("Unable to automatically find configuration.yaml, you have to specify it with -c/--config")

        to_check = [args.config, os.path.join(args.config, 'configuration.yaml')]

        for check in to_check:
            expanded = os.path.expanduser(check)
            if expanded and os.path.isfile(expanded):
                config = expanded

        if not config:
            raise ValueError("Unable to find configuration.yaml in specified location.")

    zwave = ZWave(config)
    zwave.render()
