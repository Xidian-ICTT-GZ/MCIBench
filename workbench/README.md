# MCIBench Workbench

Interactive workbench behind the SANER 2027 tool demo: it generates and
translates code for a problem, executes every candidate locally, reports the
per-language verification gates, and summarises how the candidates disagree as
*behavioural uncertainty* (spectral entropy of the candidate agreement kernel).

## Layout

    workbench/
      packages/server/     Go API server (Gin + SQLite), proxies the lab
      packages/web/        Vue 3 + Element Plus frontend
      local/               Python lab: execution, judging, behavioural metrics
      deploy/              example config, systemd unit, nginx site

The Go server is a thin API in front of the Python lab. The lab owns the
execution sandbox, the answer evidence, and the similarity / entropy metrics.

## Build

    cd packages/server && CGO_ENABLED=1 go build -o mcibench-workbench ./cmd/server
    cd packages/web   && npm ci && npm run build      # emits packages/web/dist

## Configure and run

    cp deploy/config.example.yaml packages/server/config/config.yaml
    ./mcibench-workbench -config packages/server/config/config.yaml

The server listens on 127.0.0.1 by default and spawns the lab process. The lab
is addressed with a per-run token; nothing else needs to be exposed.

## Data prerequisites

The lab reads a prepared corpus, which is not stored in this directory:

    local/testcases/<qid>/cases.json                     FT-100 case corpora
    MCIBench-test/metadata/problems/descriptions/<qid>/  problem statements
    MCIBench-test/metadata/templates/snippets/<qid>/     per-language templates
    MCIBench-test/solutions/reference/<qid>/             reference solutions

This repository keeps the same trees at the top level, so they can be linked
in place:

    mkdir -p workbench/MCIBench-test
    ln -s ../../metadata  workbench/MCIBench-test/metadata
    ln -s ../../solutions workbench/MCIBench-test/solutions

Without them the server still starts and serves the history pages, but the
problem catalog reports no verified corpora.

## Python version

The lab must run on **CPython 3.12.14**. The extension corpora record the
interpreter version that produced them, and the catalog rejects a corpus whose
recorded version differs, falling back from 232 verified problems to 100.
Install numpy for that interpreter as well.

## Deployment used for the demo

    deploy/mcibench-demo-workbench.service   systemd unit
    deploy/nginx-demo.conf                   site that fronts both apps

The demo serves the workbench at / and the base visualisation app (dashboard/)
under /legacy-app/, with /legacy-app/api/ routed to that app's own backend.
