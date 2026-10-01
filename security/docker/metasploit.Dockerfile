FROM metasploitframework/metasploit-framework:6.5.5@sha256:a05bb5cac4c4d95b2ebeb972813ce17b2da022d7647c4f17e9537bffa2906ed6

WORKDIR /usr/src/metasploit-framework

# This assessment uses a fixed outbound TCP module and does not need the
# upstream image's raw-socket or privileged-port file capabilities.
RUN setcap -r /usr/local/bin/ruby \
    && setcap -r /usr/bin/nmap \
    && chmod a-s /usr/bin/abuild-sudo \
    && test -z "$(getcap -r / 2>/dev/null)" \
    && test -z "$(find / -xdev -type f -perm /6000 -print -quit 2>/dev/null)" \
    && test -x ./msfconsole

ENV HOME=/tmp
USER 1000:1000
ENTRYPOINT []
