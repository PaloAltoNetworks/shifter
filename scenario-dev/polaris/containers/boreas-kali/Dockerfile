# base image: kali-rolling
FROM kalilinux/kali-rolling@sha256:776d57c9d607faafef9957073b0b5a05b0d1115e5728777a8fc5588827cfd249

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
