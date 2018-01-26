# home-assistant-z-wave-graph

Graph your Z-Wave mesh automatically from within Home Assistant.

![Graph](z-wave-graph-sample.png)

## Update Info

2018-01-26:
 1. Default to no SSL for the API connection. You will need to add `--ssl` to your invocation if your HA uses SSL directly (i.e. not through a proxy). 

2018-01-25:
 1. No longer using Graphviz, neither the system package nor the Python module are required. 
 1. `config/www/svg-pan-zoom.min.js` is no longer needed, you may delete it.

## Install
Install the `networkx` Python module:
```
pip3 install networkx # from INSIDE your venv if you use one
```

## Suggested Integration

### Home Assistant Configuration

Requires the following secret for the iframe url:
```
z_wave_graph_url: http://YOUR_DOMAIN_HERE:8123/local/z-wave-graph.html
```
The Python script loads your HA configuration to try to pull out the details it needs. Some installations require more tweaks. See `~/bin/z-wave-graph.py --help` for command line options.

Put all the files in their correct location (assuming you're using split configuration):
```
automation: !include_dir_merge_list automations/
shell_command: !include_dir_merge_named shell_commands/
panel_iframe: !include_dir_merge_named panel_iframe/
```

Otherwise you will have to put the fiddly bit into the right place by hand.

## Running

By default it is suppose to run every 5 minutes (`config/automations/z-wave-graph.yaml`) loading the current Z-Wave mesh. I experimented with on startup and shutdown, but the Z-Wave mesh did not exist at that point so the results were wrong.

## Graph

The graph is draggable and zoomable (mouse wheel).

The top node should be your Z-Wave controller, identified by primaryController in capabilities.

All nodes have mouse-over information with details. A **+** after the Node: id indicates a Z-Wave plus device. 

The diffent levels should correspond  to the hops in your mesh. You can click on a node to hilight the possible routes through other nodes.

Any battery powered devices will be rectangles and will have their battery level percent displayed in the mouse-over. 

## Algorithm 

The nodes and their neighbors are pulled from the HA API. networkx is then used to find all the shortest paths for each node back to the Z-Wave hub. Those edges are then graphed.

This only shows the route possibilites as there is no way to know exactly what route any particular node uses.

## Notes

Note: originally based on [home-assistant-graph](https://github.com/happyleavesaoc/home-assistant-graph) so parts may look very familiar
