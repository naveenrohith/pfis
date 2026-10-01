FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
ADD --checksum=sha256:82117377720decc99cbed02c0297f8422e2e2a3f7c4d8b3a0e4e0024919d1913 \
    https://github.com/sqlmapproject/sqlmap/archive/ea8c6bdb63a3b2da1584f328836eb0d28116f7c4.tar.gz /tmp/sqlmap.tar.gz
RUN mkdir -p /opt/sqlmap \
    && tar -xzf /tmp/sqlmap.tar.gz --strip-components=1 -C /opt/sqlmap \
    && rm /tmp/sqlmap.tar.gz
USER 65532:65532
ENTRYPOINT ["python", "/opt/sqlmap/sqlmap.py"]
