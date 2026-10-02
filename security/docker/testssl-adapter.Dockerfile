FROM ghcr.io/testssl/testssl.sh:latest@sha256:d02d3b2e03f61c20838d788b7c5102e1c5bdcf85ead96a1bc9aa8c2657d9282b
COPY security/testssl_adapter.sh /opt/pfis/testssl_adapter.sh
ENTRYPOINT ["/bin/sh", "/opt/pfis/testssl_adapter.sh"]
CMD ["--version"]
