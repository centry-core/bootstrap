#!/usr/bin/python3
# coding=utf-8
# pylint: disable=I1101

#   Copyright 2023 getcarrier.io
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

""" Module """

import os
import signal
import zipfile
import logging
import tempfile
import threading
import faulthandler

import arbiter  # pylint: disable=E0401
import requests  # pylint: disable=E0401

from pylon.core.tools import log  # pylint: disable=E0611,E0401
from pylon.core.tools import module  # pylint: disable=E0611,E0401

from .tools.repo import RepoResolver
from .tools.event import RuntimeAnnoucer
from .tools.logs import LocalListLogHandler
from .tools.signal import signal_sigusr2
from .tools.tasks import wait_for_tasks
from .tools import mesh


class Module(module.ModuleModel):  # pylint: disable=R0902
    """ Pylon module """

    def __init__(self, context, descriptor):
        self.context = context
        self.descriptor = descriptor
        #
        self.log_buffer = []
        self.log_handler = None
        #
        self.mesh_event_node = None
        self.mesh_service_node = None
        #
        self.repo_resolver = None
        #
        self.stop_event = threading.Event()
        self.announcer = None

    def init(self):  # pylint: disable=R0914
        """ Init module """
        log.info("Initializing module")
        #
        faulthandler.register(signum=signal.SIGUSR1)  # pylint: disable=E1101
        #
        if self.context.web_runtime == "gevent":
            signal.signal(signal.SIGUSR2, signal_sigusr2)  # pylint: disable=E1101
        #
        if self.descriptor.config.get("debug", False):
            logging.root.setLevel(logging.DEBUG)
            #
            self.log_handler = LocalListLogHandler(
                target_list=self.log_buffer,
            )
            self.log_handler.setFormatter(log.state.formatter)
            logging.getLogger("").addHandler(self.log_handler)
        #
        self._init_mesh(self.descriptor.config.get("mesh", {}))
        #
        self.repo_resolver = self._make_resolver()
        self.repo_resolver.init()
        #
        plugins_to_check = [
            *self.descriptor.config.get("local_preordered_plugins", []),
            *self.descriptor.config.get("customer_preordered_plugins", []),
            *self.descriptor.config.get("preordered_plugins", [])
        ]
        #
        known_plugins = set(plugins_to_check)
        plugins_provider = self.context.module_manager.providers["plugins"]
        #
        while plugins_to_check:
            plugin = plugins_to_check.pop(0)
            log.info("Preloading plugin: %s", plugin)
            #
            if plugins_provider.plugin_exists(plugin):
                log.info("Plugin %s already exists", plugin)
                #
                metadata = plugins_provider.get_plugin_metadata(plugin)
            else:
                plugin_info = self.repo_resolver.resolve(plugin)
                if plugin_info is None:
                    log.error("Plugin %s is not known", plugin)
                    continue
                #
                metadata_provider = self.repo_resolver.get_metadata_provider(plugin)
                #
                metadata_url = plugin_info["objects"]["metadata"]
                metadata = metadata_provider.get_metadata({"source": metadata_url})
                #
                source_target = plugin_info["source"].copy()
                source_type = source_target.pop("type")
                #
                if source_type not in  ["git", "http_tar", "http_zip"]:
                    log.error("Plugin %s source type %s is not supported", plugin, source_type)
                    continue
                #
                source_provider = self.repo_resolver.get_source_provider(plugin)
                #
                source = source_provider.get_source(source_target)
                plugins_provider.add_plugin(plugin, source)
            #
            for dependency in metadata.get("depends_on", []):
                if dependency in known_plugins:
                    continue
                #
                known_plugins.add(dependency)
                plugins_to_check.append(dependency)
        #
        self.descriptor.init_events()
        #
        self.announcer = RuntimeAnnoucer(self, {})
        self.announcer.start()

    def _init_mesh(self, mesh_config):
        if "event_node" not in mesh_config:
            return
        #
        self.mesh_event_node = arbiter.make_event_node(
            config=mesh_config.get("event_node"),
        )
        self.mesh_event_node.start()
        #
        self.mesh_service_node = arbiter.ServiceNode(
            event_node=self.mesh_event_node,
            id_prefix=f"mesh:id:{self.context.id}:",
            default_timeout=120,
        )
        self.mesh_service_node.start()
        #
        self.mesh_service_node.register(
            callback=mesh.get_plugin_frozen_requirements,
            name=f"mesh:service:{self.context.id}:get_plugin_frozen_requirements",
        )

    def _deinit_mesh(self):
        if self.mesh_service_node is not None:
            self.mesh_service_node.unregister(
                callback=mesh.get_plugin_frozen_requirements,
                name=f"mesh:service:{self.context.id}:get_plugin_frozen_requirements",
            )
            #
            self.mesh_service_node.stop()
        #
        if self.mesh_event_node is not None:
            self.mesh_event_node.stop()

    def _make_resolver(self):
        resolvers = []
        #
        for key in ["local_plugin_repo", "customer_plugin_repo", "plugin_repo"]:
            if key in self.descriptor.config:
                resolvers.append(self.descriptor.config[key])
        #
        return RepoResolver(self, resolvers)

    def reconfig(self):
        """ Re-config module """
        log.info("Re-configuring module")
        #
        if self.repo_resolver is not None:
            self.repo_resolver.deinit()
        #
        self.repo_resolver = self._make_resolver()
        self.repo_resolver.init()

    def unready(self):
        """ Un-ready callback """
        try:
            wait_for_tasks(self)
        except:  # pylint: disable=W0702
            pass

    def deinit(self):
        """ De-init module """
        log.info("De-initializing module")
        #
        self.stop_event.set()
        self.announcer.join(3.0)
        #
        self.context.event_manager.fire_event(
            "bootstrap_runtime_info_prune",
            {
                "pylon_id": self.context.id,
            },
        )
        #
        if self.repo_resolver is not None:
            self.repo_resolver.deinit()
        #
        self._deinit_mesh()

    def get_bundle(self, name, **kwargs):  # pylint: disable=R0912,R0914
        """ Bundle """
        session = None
        target_url = None
        #
        if self.repo_resolver is not None:
            config = self.repo_resolver.repo_config
            #
            while isinstance(config, list):
                config = config[0]
            #
            if config.get("type", "unknown") == "repo_depot":
                session = requests.Session()
                session.headers.update({
                    "User-Agent": "PythonMachineryEliteAClient",
                })
                #
                release = config.get("release", "main")
                license_token = config.get("license_token", None)
                repo_url = config.get("repo_url", "https://repo.elitea.ai/target")
                #
                repo_url_base = repo_url.rstrip("/")
                #
                if license_token is not None:
                    session.headers.update({
                        "Authorization": f"Bearer {license_token}",
                    })
                else:
                    repo_url_base = f"{repo_url_base}/public"
                #
                target_url = f"{repo_url_base}/depot/{release}/bundles/{name}/data"
        #
        if session is None:
            raise RuntimeError("RepoResolver is not for depot")
        #
        processing = kwargs.get("processing", None)
        #
        if processing == "zip_extract" and "extract_target" in kwargs:
            extract_target = kwargs["extract_target"]
            extract_cleanup = kwargs.get("extract_cleanup", False)
            extract_cleanup_skip_files = kwargs.get("extract_cleanup_skip_files", [])
            extract_cleanup_skip_dirs = kwargs.get("extract_cleanup_skip_dirs", [])
            #
            with tempfile.TemporaryFile() as temp_file:
                with session.get(target_url, stream=True) as response:
                    response.raise_for_status()
                    #
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)
                #
                temp_file.seek(0)
                #
                with zipfile.ZipFile(temp_file) as zip_file:
                    if extract_cleanup:
                        for root, dirs, files in os.walk(extract_target, topdown=False):
                            for file_name in files:
                                if file_name in extract_cleanup_skip_files:
                                    continue
                                #
                                try:
                                    os.remove(os.path.join(root, file_name))
                                except:  # pylint: disable=W0702
                                    log.exception("Failed to remove file: %s, skipping", file_name)
                            #
                            for dir_name in dirs:
                                if dir_name in extract_cleanup_skip_dirs:
                                    continue
                                #
                                try:
                                    os.rmdir(os.path.join(root, dir_name))
                                except:  # pylint: disable=W0702
                                    log.exception("Failed to remove dir: %s, skipping", dir_name)
                    #
                    zip_file.extractall(extract_target)
            #
            log.info("Bundle ZIP extracted: %s -> %s", name, extract_target)
            #
            return
        #
        raise RuntimeError("Unknown processing type")
