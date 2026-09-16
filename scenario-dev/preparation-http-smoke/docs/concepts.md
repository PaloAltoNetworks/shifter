# Preparation HTTP smoke

A contained HTTP service on Ubuntu 22.04. The pack declares the compute service
and a permitted preparation recipe; it grants no execution authority. Its
network realization is open, so the runtime-selected backend adapter must
provide an isolated network. Install and approve the preparation adapter
separately. The service responds on port 8080 and has no external targets.
