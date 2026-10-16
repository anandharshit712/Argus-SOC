# Throwaway SSH brute-force target for the live demo (Workstream A, demo harness).
# Internal network only -- never published. One dummy account with an unguessable password, so
# every brute-force attempt the attack-bot makes fails, exactly as the demo needs.
#
# rsyslog writes the auth facility to /var/log/auth.log in the standard
# "Mmm d HH:MM:SS <host> sshd[pid]: ..." syslog shape Talos's NetworkLogParser reads. The host
# name in each line is the container hostname, set to bastion-01 in the compose file.
FROM debian:12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server rsyslog \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /var/log \
    && useradd -m -s /bin/bash svc_deploy \
    && echo 'svc_deploy:correct-horse-battery-staple-ssh' | chpasswd
# Log auth attempts verbosely so every failure is written.
RUN sed -i 's/^#\?LogLevel.*/LogLevel VERBOSE/' /etc/ssh/sshd_config
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 22
CMD ["/start.sh"]
