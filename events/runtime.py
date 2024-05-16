#!/usr/bin/python3
# coding=utf-8

#   Copyright 2024 getcarrier.io
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

""" Event """

from pylon.core.tools import log, web  # pylint: disable=E0611,E0401


class Event:  # pylint: disable=R0903,E1101
    """ Event """

    @web.event("bootstrap_runtime_update")
    def _bootstrap_runtime_update(self, context, event, payload):  # pylint: disable=R0914
        _ = context, event
        #
        if not isinstance(payload, dict):
            return
        #
        if self.context.id != payload.get("pylon_id", ""):
            return
        #
        module_manager = self.context.module_manager
        plugins_provider = module_manager.providers["plugins"]
        repo_resolver = self.repo_resolver
        #
        for plugin in payload.get("plugins", []):
            if plugin.startswith("!"):
                plugin = plugin.rstrip("!")
                log.info("Deleting plugin: %s", plugin)
                #
                if plugins_provider.plugin_exists(plugin):
                    plugins_provider.delete_plugin(plugin)
            else:
                if plugins_provider.plugin_exists(plugin):
                    log.info("Updating plugin: %s", plugin)
                else:
                    log.info("Installing plugin: %s", plugin)
                #
                plugin_info = repo_resolver.resolve(plugin)
                #
                if plugin_info is None:
                    log.error("Plugin is not known by repo resolver(s)")
                    continue
                #
                metadata_provider = repo_resolver.get_metadata_provider(plugin)
                #
                metadata_url = plugin_info["objects"]["metadata"]
                metadata = metadata_provider.get_metadata({"source": metadata_url})
                #
                source_target = plugin_info["source"].copy()
                source_type = source_target.pop("type")
                #
                if source_type != "git":
                    log.error("Plugin source type is not supported: %s", source_type)
                    continue
                #
                source_provider = repo_resolver.get_source_provider(plugin)
                source = source_provider.get_source(source_target)
                #
                plugins_provider.add_plugin(plugin, source)
                log.info("Plugin updated to version %s", metadata.get("version", "0.0.0"))
        #
        if payload.get("restart", True):
            import os  # pylint: disable=C0415
            import subprocess  # pylint: disable=C0415
            #
            pylon_pid = os.getpid()
            #
            log.info("Restarting pylon (pid = %s)", pylon_pid)
            subprocess.Popen(  # pylint: disable=R1732
                    ["/bin/bash", "-c", f"bash -c 'sleep 1; kill {pylon_pid}' &"]
            )
