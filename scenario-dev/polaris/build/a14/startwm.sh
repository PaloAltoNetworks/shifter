#!/bin/bash
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
if [ -r /etc/profile ]; then
    . /etc/profile
fi
exec startxfce4
