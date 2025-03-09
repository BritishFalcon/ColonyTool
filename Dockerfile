FROM ubuntu:latest
LABEL authors="Ben"

ENTRYPOINT ["top", "-b"]