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
COPY run.sh /
COPY config/shell_commands/z-wave-graph.yaml shell_commands_z-wave-graph.yaml

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
