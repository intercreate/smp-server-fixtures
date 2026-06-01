# Copyright (c) 2017 Open Source Foundries Limited
# Copyright (c) 2025 Intercreate, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# De-vendored: application sources come from the upstream Zephyr smp_svr sample
# (pinned by west.yml), not a local copy. This repo owns only the fixture
# configs (prj.conf, *.conf, boards/) and sample.yaml.
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(smp_svr)

set(SMP_SVR $ENV{ZEPHYR_BASE}/samples/subsys/mgmt/mcumgr/smp_svr)
target_sources(app PRIVATE ${SMP_SVR}/src/main.c)
target_sources_ifdef(CONFIG_MCUMGR_TRANSPORT_BT app PRIVATE ${SMP_SVR}/src/bluetooth.c)
