#! /home/homeassistant/bin/python3

import datetime
import argparse
import os.path

import homeassistant.remote as remote
import homeassistant.config

from graphviz import Digraph


class ZWave(object):
    def __init__(self, config):
        self.connections = {}
        self.primary_controller = []

        self.haconf = homeassistant.config.load_yaml_config_file(config)

        self.directory = os.path.join(os.path.dirname(config), 'www')
        self.filename = 'z-wave-graph'

        api_password = None
        if 'api_password' in self.haconf['http']:
            api_password = self.haconf['http']['api_password']

        use_ssl = False
        if 'ssl_key' in self.haconf['http']:
            use_ssl = True

        base_url = self.haconf['http']['base_url']
        if ':' in base_url:
            base_url = base_url.split(':')[0]

        self.api = remote.API(base_url, api_password, use_ssl=use_ssl)

        self.dot = Digraph(comment='Home Assistant Z-Wave Graph', format='svg', engine='neato')

        self.dot.attr(overlap='false')

        # http://matthiaseisen.com/articles/graphviz/
        self.dot.graph_attr.update({
            'label': r'Z-Wave Node Connections\nLast updated: ' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fontsize': '24',
            # 'rankdir': 'BT',
        })

        self._get_entities()
        self._build_connections()


    def _get_entities(self):

        entities = remote.get_states(self.api)
        for entity in entities:
            if entity.entity_id.startswith('zwave'):
                node_id = str(entity.attributes['node_id'])

                try:
                    neighbors = entity.attributes['neighbors']
                except KeyError:
                    neighbors = []

                extra = {}
                try:
                    if 'primaryController' in entity.attributes['capabilities']:
                        # Make any Z-Wave node that is a primaryController stand out.
                        extra['fillcolor'] = 'chartreuse'
                        extra['style'] = "rounded,filled"
                        self.primary_controller.append(node_id)
                except KeyError:
                    pass

                name = entity.attributes['friendly_name']

                name += " [%s" % node_id

                if entity.attributes['is_zwave_plus']:
                    name += "+"
                else:
                    name += "-"
                name += "]\n(%s" % entity.attributes['product_name']

                try:
                    name += ": %s%%" % entity.attributes['battery_level']
                except KeyError:
                    pass

                name += ")"

                self.dot.node(node_id, name, extra)

                for neighbor in neighbors:
                    if node_id not in self.connections:
                        self.connections[node_id] = {}

                    self.connections[node_id][str(neighbor)] = True


    def _build_connections(self):
        for key in sorted(self.connections):
            nodes = self.connections[key]
            for node in nodes.keys():
                extra = {'dir': 'both'}
                if key in self.primary_controller:
                    extra['color'] = 'green'
                    extra['penwidth'] = '3'

                self.dot.edge(key, node, **extra)

                try:
                    # This bit of trickery is to work around the fact that A -> B and usually B -> A too.
                    del(self.connections[node][key])
                except KeyError:
                    pass


    def render(self):
        self.dot.render(filename=self.filename, directory=self.directory)


if __name__ == '__main__':
    """Generate graph of Home Assistant Z-Wave devices."""
    to_check = ['~/.config/configuration.yaml', '~/config/configuration.yaml']
    config = None

    for check in to_check:
        expanded = os.path.expanduser(check)
        if os.path.isfile(expanded):
            config = expanded
            
    parser = argparse.ArgumentParser()
    if not config:
        print("Unable to automatically find configuration.yaml, you have to specify it.")
        parser.add_argument('-i', '--config', help='path to configuration.yaml', required=True)

    zwave = ZWave(config)
    zwave.render()