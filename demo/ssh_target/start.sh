#!/bin/sh
# rsyslog (writes /var/log/auth.log) then sshd in the foreground.
rsyslogd
exec /usr/sbin/sshd -D -e
