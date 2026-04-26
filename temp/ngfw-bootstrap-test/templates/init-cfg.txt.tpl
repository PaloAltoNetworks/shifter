type=dhcp-client
hostname=${hostname}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
%{ if pin_id != "" ~}
panorama-server=cloud
vm-series-auto-registration-pin-id=${pin_id}
vm-series-auto-registration-pin-value=${pin_value}
%{ endif ~}
%{ if dgname != "" ~}
dgname=${dgname}
%{ endif ~}
