# Throwaway SSH brute-force target for the live demo (Workstream A, demo harness).
# Internal network only -- never published. One dummy account with an unguessable password, so
# every brute-force attempt the attack-bot makes fails, exactly as the demo needs.
#
# rsyslog writes the auth facility to /var/log/auth.log in the standard
# "Mmm d HH:MM:SS <host> sshd[pid]: ..." syslog shape Talos's NetworkLogParser reads. The host
# name in each line is the container hostname, set to bastion-01 in the compose file.
FROM debian:12-slim
# Dummy password for the throwaway account (rule 12: no secret baked in; override at build).
# Irrelevant to detection anyway -- the attack-bot always guesses wrong.
ARG SSH_TARGET_PASSWORD=correct-horse-battery-staple-ssh
# Pool accounts ops001..opsNNN the bot really logs into on an SSH "pass" run (ATTACK_BOT_PASS_FAIL
# §6). All share DEMO_SSH_POOL_PASSWORD; a fresh one per pass keeps each success a new signature.
ARG DEMO_SSH_POOL_PASSWORD=change-me-ssh-pool
ARG DEMO_SSH_POOL_SIZE=300
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server rsyslog \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /var/log \
    && useradd -m -s /bin/bash svc_deploy \
    && echo "svc_deploy:${SSH_TARGET_PASSWORD}" | chpasswd \
    && for i in $(seq 1 ${DEMO_SSH_POOL_SIZE}); do \
         u=$(printf 'ops%03d' "$i"); \
         useradd -m -s /bin/bash "$u" && echo "$u:${DEMO_SSH_POOL_PASSWORD}" | chpasswd; \
       done
# Log auth attempts verbosely so every failure is written.
RUN sed -i 's/^#\?LogLevel.*/LogLevel VERBOSE/' /etc/ssh/sshd_config
# Debian 12 rsyslog defaults to high-precision RFC3339 timestamps; Talos's NetworkLogParser reads
# the traditional "Mmm d HH:MM:SS" syslog stamp, so force that format.
RUN printf '$ActionFileDefaultTemplate RSYSLOG_TraditionalFileFormat\n' > /etc/rsyslog.d/00-traditional.conf
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 22
CMD ["/start.sh"]
