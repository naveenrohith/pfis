FROM ghcr.io/zaproxy/zaproxy:stable@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef
COPY security/zap_authenticated.py /opt/pfis/zap_authenticated.py
COPY security/zap_passive.py /opt/pfis/zap_passive.py
COPY security/zap_api_hooks.py /opt/pfis/zap_api_hooks.py
COPY security/zap_csrf_cookie_header.js /opt/pfis/zap_csrf_cookie_header.js
ENTRYPOINT ["python3", "/opt/pfis/zap_authenticated.py"]
