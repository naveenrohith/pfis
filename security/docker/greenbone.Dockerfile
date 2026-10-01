FROM registry.community.greenbone.net/community/gvm-tools:latest@sha256:a3ec2b8d2281e1a0bea147f1a6fbe00d22eab26db1c114bebf7bb2beed0a5619
COPY security/greenbone_adapter.py /opt/pfis/greenbone_adapter.py
ENTRYPOINT ["python3", "/opt/pfis/greenbone_adapter.py"]
