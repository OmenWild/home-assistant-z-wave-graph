#! /usr/bin/env python3

import argparse
import datetime
import json
import locale
import os.path
import site
import sys

from requests import get

locale.setlocale(locale.LC_ALL, '')

# Needed for the docker image:
# https://community.home-assistant.io/t/graph-your-z-wave-mesh-python-auto-update/40549/87?u=omenwild
if os.path.isdir('/usr/src/app'):
    sys.path.append('/usr/src/app')


def need(what):
    print("Error unable to import the module `%s', please pip install it" % what, end='')
    if (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)):
        print(" from WITHIN your virtual environment", end='')
    print(".\n")
    sys.exit(1)


# Add persistent site packages if in docker
if os.path.isdir('/config/deps/lib/python3.6/site-packages'):
    site.addsitedir('/config/deps/lib/python3.6/site-packages')

try:
    import networkx as nx
except ImportError:
    need('networkx')

import homeassistant.config
import homeassistant.const


class Node(object):
    def __init__(self, attrs):
        self.attrs = attrs
        self.rank = None

        self.neighbors = []
        # Special case this one so __getattr__ can return None intead of KeyError for other lookups.
        if 'neighbors' in self.attrs:
            self.neighbors = sorted(self.attrs['neighbors'])

        self.primary_controller = False
        try:
            if 'primaryController' in self.capabilities:
                # Make any Z-Wave node that is a primaryController stand out.
                self.primary_controller = True
        except (KeyError, TypeError):
            pass

        self.forwarder = True
        if self.is_awake == False or \
                self.is_ready == False or \
                self.is_failed == True or \
                'listening' not in self.capabilities:
            self.forwarder = False


    def __getattr__(self, name):
        if name in self.attrs:
            return self.attrs[name]
        else:
            return None


    @property
    def id(self):
        return self.node_id


    def __str__(self):
        if self.primary_controller:
            return "Z-Wave Hub\n%s" % datetime.datetime.now().strftime('%b %d\n%H:%M')
        else:
            return "{}{!s} ({:n})".format(self.friendly_name, '!!!' if self.is_failed else '', self.averageRequestRTT).replace(' ', "\n")


    def title(self):
        title = ""

        if self.is_failed:
            title += "<b>FAILED: </b>"

        title += "<b>%s</b><br/>" % self.friendly_name

        title += "Node: %s" % self.node_id

        if self.is_zwave_plus:
            title += "<b>+</b>"

        title += "<br/>Product Name: %s" % self.product_name

        if self.battery_level:
            title += "<br/>Battery: %s%%" % self.battery_level

        title += "<br/>Average Request RTT: {:n}ms".format(self.averageRequestRTT)

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

        self.outpath = args.outpath or \
                       os.path.join(os.path.dirname(config), 'www', 'z-wave-graph.json')

        # API connection necessities.
        self.api_password = None
        self.api_token = None

        if args.url:
            self.base_url = args.url
        else:
            self.base_url = 'http://localhost:%s' % homeassistant.const.SERVER_PORT

        if 'HASSIO_TOKEN' in os.environ:
            self.api_password = os.environ['HASSIO_TOKEN']
        elif self.args.token:
            self.api_token = self.args.token
        else:
            raise ValueError("No HASSIO_TOKEN in the environment and --token not specified")

        m = self.request('/')
        if 'message' not in m or m['message'] != 'API running.':
            raise RuntimeError("Error, unable to connect to the API at %s" % self.base_url)

        self.get_entities()

        if self.args.debug:
            self.dump_nodes()

        self.build_graph()


    def request(self, path):
        url = '%s/api%s' % (self.base_url, path)
        headers = {'x-ha-access': self.api_password,
                   'Authorization': 'Bearer {}'.format(self.api_token),
                   'content-type': 'application/json'}

        response = get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError("Unable to pull the data from: %s" % url, response.text)

        # print("request(%s):\n" % (path), response.text)

        return json.loads(response.text)


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


    def get_entities(self):
        entities = self.request('/states')
        for entity in entities:
            if entity['entity_id'].startswith('zwave.'):
                self.add(entity['attributes'])


    def build_graph(self):
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

            self.json['nodes'].append({'id': "{} (#{})".format(node.friendly_name, node.id), **config})

        for node in self.nodes:
            for path in node.shortest:
                for edge in path[1:2]:  # Only graph the first hop in each node.
                    edge = self.nodes.nodes[edge]

                    config = {}
                    if node == edge:
                        # Skip myself
                        continue

                    if not edge.forwarder:
                        # Skip edges that go through devices that look like they don't forward.
                        continue

                    # config['value'] = 1.0 / node.rank
                    _from = "{} (#{})".format(node.friendly_name, node.id)
                    _to = "{} (#{})".format(edge.friendly_name, edge.id)
                    self.json['edges'].append({'from': _from, 'to': _to, **config})


    def render(self):
        if self.args.debug:
            print(self.json)

        with open(self.outpath, 'w') as outfile:
            json.dump(self.json, outfile, indent=2, sort_keys=True)


    @staticmethod
    def find_config(paths=None):
        if not paths:
            paths = ['~/.config/', '~/config/', '~/.homeassistant/', '~/homeassistant/', '/config/']

        for path in paths:
            expanded = os.path.expanduser(path)
            if os.path.isfile(expanded):
                return expanded

            expanded = os.path.expanduser(os.path.join(path, 'configuration.yaml'))
            if os.path.isfile(expanded):
                return expanded

        return None



if __name__ == '__main__':
    """Generate graph of Home Assistant Z-Wave devices."""

    parser = argparse.ArgumentParser(description='Generate a Z-Wave mesh from your Home Assistant system.')
    parser.add_argument('--config', default=None, help='path to configuration.yaml if auto-detect fails')
    parser.add_argument('--debug', action="store_true", dest='debug', default=False, help='print debug output')
    parser.add_argument('--token', type=str, default=None, help='long lived access token')
    parser.add_argument('--outpath', type=str, default=None, help='path to write .json file output to')
    parser.add_argument('--url', type=str, default=None, help='The URL of the HA server, including port and https if necessary')
    args = parser.parse_args()

    if args.config:
        config = ZWave.find_config([args.config, os.path.join(args.config, 'configuration.yaml')])
        if not config:
            raise ValueError("Unable to find configuration.yaml in specified location.")
    else:
        config = ZWave.find_config()

    if not config:
        raise ValueError("Unable to automatically find configuration.yaml, you have to specify it with -c/--config")

    zwave = ZWave(config, args)
    zwave.render()
