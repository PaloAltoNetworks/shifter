FROM alpine:3.19

RUN apk add --no-cache nmap nmap-scripts nmap-ncat tcpdump python3 py3-pip openssh bash && \
    pip3 install --break-system-packages pymodbus==3.12.1 && \
    ssh-keygen -A && mkdir /run/sshd

# Content files live in A9-splice-landing/ per convention; build context
# is the parent mechag/ dir.
COPY A9-splice-landing/README.txt /root/README.txt
COPY A9-splice-landing/scan_results.txt /root/scan_results.txt
COPY A9-splice-landing/modbus_client.py /usr/local/bin/modbus_client.py
RUN chmod +x /usr/local/bin/modbus_client.py

# Set root password for SSH access
RUN echo "root:splice2025" | chpasswd

# Allow root SSH login
RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
