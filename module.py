#!/usr/bin/python3
# coding=utf-8

#   Copyright 2021 getcarrier.io
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

import json
import importlib

from pylon.core.tools import log  # pylint: disable=E0611,E0401
from pylon.core.tools import module  # pylint: disable=E0611,E0401


class Module(module.ModuleModel):
    """ Pylon module """

    def __init__(self, context, descriptor):
        self.context = context
        self.descriptor = descriptor

    def init(self):
        """ Init module """
        log.info("Initializing module")
        #
        if self.descriptor.config["plugin_repo"]["type"] == "resource":
            plugin_repo = json.loads(
                self.descriptor.loader.get_data(self.descriptor.config["plugin_repo"]["name"])
            )
        else:
            plugin_repo = None
        #
        if plugin_repo is None:
            log.error("No plugin repo loaded!")
            return
        #
        plugins_to_check = self.descriptor.config["preordered_plugins"]
        known_plugins = set(plugins_to_check)
        #
        plugins_provider = self.context.module_manager.providers["plugins"]
        #
        metadata_provider = importlib.import_module(
            "pylon.core.providers.metadata.http"
        ).Provider(self.context, {})
        metadata_provider.init()
        #
        source_provider = importlib.import_module(
            "pylon.core.providers.source.git"
        ).Provider(self.context, {"delete_git_dir": False})
        source_provider.init()
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
                if plugin not in plugin_repo:
                    log.error("Plugin %s is not known", plugin)
                    continue
                #
                metadata_url = plugin_repo[plugin]["objects"]["metadata"]
                source_url = plugin_repo[plugin]["source"]["url"]
                #
                metadata = metadata_provider.get_metadata({"source": metadata_url})
                #
                source = source_provider.get_source({"source": source_url})
                plugins_provider.add_plugin(plugin, source)
            #
            for dependency in metadata.get("depends_on", list()):
                if dependency in known_plugins:
                    continue
                #
                known_plugins.add(dependency)
                plugins_to_check.append(dependency)
        #
        source_provider.deinit()
        metadata_provider.deinit()

    def deinit(self):  # pylint: disable=R0201
        """ De-init module """
        log.info("De-initializing module")
