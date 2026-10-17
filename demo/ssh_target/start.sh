#!/bin/sh
# rsyslog (writes /var/log/auth.log) then sshd in the foreground.
# No -e: sshd must log "Failed password ..." to syslog, not stderr, so rsyslog captures it in the
# shape Talos's NetworkLogParser reads.
rsyslogd
exec /usr/sbin/sshd -D
