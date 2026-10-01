#!/bin/bash
# A throwaway CA + wildcard certificate for *.syd.accfino.test, so the real app can be tested over HTTPS with organisation sub-domains. TEST USE ONLY.
mkdir -p /tmp/wild && cd /tmp/wild || exit 1
openssl genrsa -out ca.key 2048 2>/dev/null
openssl req -x509 -new -key ca.key -sha256 -days 3 -subj "/CN=Local Test CA" -out ca.pem 2>/dev/null
openssl genrsa -out srv.key 2048 2>/dev/null
openssl req -new -key srv.key -subj "/CN=*.syd.accfino.test" -out srv.csr 2>/dev/null
printf "subjectAltName=DNS:*.syd.accfino.test,DNS:syd.accfino.test\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n" > ext.cnf
openssl x509 -req -in srv.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 3 -sha256 -extfile ext.cnf -out srv.pem 2>/dev/null
openssl verify -CAfile ca.pem srv.pem
