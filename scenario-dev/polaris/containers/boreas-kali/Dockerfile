FROM kalilinux/kali-rolling

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      kali-linux-top10 openssh-server xrdp nodejs npm python3 python3-pip \
      ca-certificates sudo \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd

RUN useradd -m -s /bin/bash kali && echo 'kali:kali' | chpasswd && usermod -aG sudo kali

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 3389
CMD ["/entrypoint.sh"]
