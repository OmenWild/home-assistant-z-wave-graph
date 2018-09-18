ARG BUILD_FROM
FROM $BUILD_FROM

# Add env
ENV LANG C.UTF-8

RUN apk add --no-cache python3

# install .py script dependency
RUN pip3 install networkx

# Copy data for add-on
COPY bin/z-wave-graph.py /

COPY config/www/z-wave-graph.html /
COPY config/shell_commands/z-wave-graph-hassio-addon.yaml shell_commands_z-wave-graph.yaml
COPY config/automations/z-wave-graph.yaml automations_z-wave-graph.yaml

COPY run.sh /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
