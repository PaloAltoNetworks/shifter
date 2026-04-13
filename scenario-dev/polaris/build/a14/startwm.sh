#!/bin/bash
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
if [ -r /etc/profile ]; then
    . /etc/profile
fi

# Even with xfce4-screensaver purged from the image, belt-and-suspenders:
# make sure the X server itself never blanks or DPMS-powers-off the display
# on idle RDP sessions during the CTF event.
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset -dpms 2>/dev/null || true

exec startxfce4
