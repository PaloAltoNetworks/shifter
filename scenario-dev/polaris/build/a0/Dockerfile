FROM python:3.12-slim AS content-builder
RUN pip install --no-cache-dir reportlab
WORKDIR /build
COPY A0-boreas-website/build_pdfs.py .
# The CTFd board is the canonical flag source for the generated PDFs
# (flag 6 lives on the annual report); build_pdfs.py reads it as a sibling.
COPY ctfd-challenges.json .
RUN python build_pdfs.py /build/out

FROM nginx:alpine
COPY A0-boreas-website/site/ /usr/share/nginx/html/
COPY --from=content-builder /build/out/internal/ /usr/share/nginx/html/internal/
COPY a0/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
